"""AI backend.

- .ai (chat teks)      -> opencode CLI (default) atau Gemini.
- .img / .imgedit foto  -> Gemini (opencode CLI tidak bisa generate foto).
"""
import asyncio
import base64
import json
import os
import re
import shutil
import tempfile
import urllib.request
from pathlib import Path

from telethon import events

from core import config, helpers
from core.state import state

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _provider():
    choice = (config.get("AI_PROVIDER", "") or "auto").strip().lower()
    has_key = bool(config.GEMINI_KEY)
    has_bin = shutil.which("opencode") is not None
    if choice == "opencode":
        return "opencode" if has_bin else "gemini"
    if choice == "gemini":
        return "gemini" if has_key else ""
    if has_bin:
        return "opencode"
    return "gemini" if has_key else ""


def _model():
    m = config.get("OPENCODE_MODEL", "").strip()
    if m:
        return m
    if config.GEMINI_KEY:
        return f"google/{config.GEMINI_MODEL}"
    return "opencode/big-pickle"


def _auth_path():
    return Path.home() / ".local" / "share" / "opencode" / "auth.json"


def _ensure_auth():
    auth = config.get("OPENCODE_AUTH_JSON", "").strip()
    if not auth:
        return
    path = _auth_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        json.loads(auth)
        path.write_text(auth, encoding="utf-8")
    except Exception:
        pass


async def ask_opencode(question, context=""):
    exe = shutil.which("opencode")
    if not exe:
        return "❌ opencode CLI tidak terpasang di server."
    _ensure_auth()
    prompt = (context + "\n\n" + question) if context else question
    cmd = [exe, "run", "--model", _model()]
    env = dict(os.environ)
    if config.GEMINI_KEY:
        env["GEMINI_API_KEY"] = config.GEMINI_KEY
        env["GOOGLE_API_KEY"] = config.GEMINI_KEY
    cwd = Path(tempfile.gettempdir())

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env, cwd=str(cwd),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=240)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return "❌ Waktu proses AI habis."
    except Exception:
        return "❌ Gagal menjalankan opencode."

    if proc.returncode != 0:
        err = stderr.decode("utf-8", "replace")[-300:]
        return f"❌ opencode error: {err}"
    text = ANSI_RE.sub("", stdout.decode("utf-8", "replace"))
    lines = [re.sub(r"^\s*[✓✔✗✖]\s*", "", l) for l in text.splitlines()]
    text = "\n".join(lines).strip()
    return text if text else "(kosong)"


async def ask_gemini(question, context=""):
    if not config.GEMINI_KEY:
        return "❌ GEMINI_KEY belum diatur."
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{config.GEMINI_MODEL}:generateContent?key={config.GEMINI_KEY}"
    )
    prompt = (context + "\n\n" + question) if context else question
    payload = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode()
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )

    def _call():
        with urllib.request.urlopen(req, timeout=90) as resp:
            return json.loads(resp.read().decode())

    try:
        data = await asyncio.to_thread(_call)
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        return "❌ Gagal memproses permintaan AI."


async def ask_ai(question, context=""):
    provider = _provider()
    if not provider:
        return "❌ AI nonaktif — set GEMINI_KEY di .env."
    if provider == "opencode":
        answer = await ask_opencode(question, context)
        if answer.startswith("❌"):
            return await ask_gemini(question, context)
        return answer
    return await ask_gemini(question, context)


def _gemini_img_url(model):
    return (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={config.GEMINI_KEY}"
    )


async def _gemini_img(prompt, image_b64="", mime="image/jpeg"):
    """Generate (tanpa image) atau edit (dengan image) via Gemini image model.
    Return (pesan_error_atau_None, daftar_bytes_gambar)."""
    if not config.GEMINI_KEY:
        return "❌ GEMINI_KEY belum diatur.", []
    model = config.GEMINI_IMG_MODEL
    parts = [{"text": prompt}]
    if image_b64:
        parts.append({"inlineData": {"mimeType": mime, "data": image_b64}})
    payload = json.dumps({
        "contents": [{"parts": parts}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
    }).encode()
    req = urllib.request.Request(
        _gemini_img_url(model), data=payload,
        headers={"Content-Type": "application/json"},
    )

    def _call():
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read().decode())

    try:
        data = await asyncio.to_thread(_call)
    except Exception:
        return "❌ Gagal memproses foto (rate limit / API down).", []

    images = []
    for part in data.get("candidates", [{}])[0].get("content", {}).get("parts", []):
        if "inlineData" in part:
            try:
                images.append(base64.b64decode(part["inlineData"]["data"]))
            except Exception:
                pass
    if not images:
        return "❌ Tidak ada gambar dihasilkan (prompt diblokir / gagal).", []
    return None, images


def chunks(text, size=4000):
    return [text[i:i + size] for i in range(0, len(text), size)] if text else ["(kosong)"]


def load():
    client = state.client

    @client.on(events.NewMessage(pattern=helpers.cmd("ai", r"\s+"), outgoing=True))
    async def ai(event):
        if not _provider():
            await helpers.temp(event, helpers.wm("❌ AI belum diatur — isi GEMINI_KEY di .env"))
            await event.delete()
            return
        question = event.message.message.split(None, 1)[1].strip()
        reply = await event.get_reply_message()
        context = reply.message if reply else ""
        note = await event.respond(helpers.wm("🤔 Memproses..."))
        answer = await ask_ai(question, context)
        try:
            await note.delete()
        except Exception:
            pass
        for part in chunks(answer):
            await event.respond(helpers.wm(part))
        await event.delete()

    @client.on(events.NewMessage(pattern=helpers.cmd("img", r"\s+"), outgoing=True))
    async def img(event):
        if not config.GEMINI_KEY:
            await helpers.temp(event, helpers.wm("❌ GEMINI_KEY belum diatur — .img butuh Gemini."))
            await event.delete()
            return
        prompt = event.message.message.split(None, 1)[1].strip()
        reply = await event.get_reply_message()
        image_b64 = ""
        mode = "🎨 Menggambar..."
        if reply and reply.photo:
            try:
                img = await client.download_media(reply, file=bytes)
                image_b64 = base64.b64encode(img).decode()
                mode = "✏️ Mengedit foto..."
            except Exception:
                image_b64 = ""
        note = await event.respond(helpers.wm(mode))
        err, images = await _gemini_img(prompt, image_b64)
        if err:
            try:
                await note.delete()
            except Exception:
                pass
            await event.respond(helpers.wm(err))
            await event.delete()
            return
        try:
            for i, raw in enumerate(images[:4]):
                path = Path(tempfile.gettempdir()) / f"img_{i}_{len(raw)}.png"
                path.write_bytes(raw)
                await event.respond(helpers.wm(f"🖼 {prompt}"), file=str(path))
                await asyncio.sleep(1)
            await note.delete()
        except Exception:
            await event.respond(helpers.wm("❌ Gagal kirim gambar."))
        await event.delete()

    @client.on(events.NewMessage(pattern=helpers.cmd("imgedit", r"\s+"), outgoing=True))
    async def imgedit(event):
        if not config.GEMINI_KEY:
            await helpers.temp(event, helpers.wm("❌ GEMINI_KEY belum diatur — .imgedit butuh Gemini."))
            await event.delete()
            return
        prompt = event.message.message.split(None, 1)[1].strip()
        reply = await event.get_reply_message()
        if not reply or not reply.photo:
            await helpers.temp(event, helpers.wm("❌ Reply ke foto yang mau diedit."))
            await event.delete()
            return
        note = await event.respond(helpers.wm("✏️ Mengedit foto..."))
        try:
            img = await client.download_media(reply, file=bytes)
        except Exception:
            await event.respond(helpers.wm("❌ Gagal download foto."))
            await event.delete()
            return
        image_b64 = base64.b64encode(img).decode()
        err, images = await _gemini_img(prompt, image_b64)
        if err:
            try:
                await note.delete()
            except Exception:
                pass
            await event.respond(helpers.wm(err))
            await event.delete()
            return
        try:
            for i, raw in enumerate(images[:4]):
                path = Path(tempfile.gettempdir()) / f"edit_{i}_{len(raw)}.png"
                path.write_bytes(raw)
                await event.respond(helpers.wm(f"✏️ {prompt}"), file=str(path))
                await asyncio.sleep(1)
            await note.delete()
        except Exception:
            await event.respond(helpers.wm("❌ Gagal kirim gambar."))
        await event.delete()

    @client.on(events.NewMessage(pattern=helpers.cmd("ailist"), outgoing=True))
    async def ailist(event):
        provider = _provider()
        status = "❌ Nonaktif — set GEMINI_KEY di .env" if not provider else \
            f"✅ Aktif\nProvider: `{provider}`\nModel: `{_model()}`"
        img_status = "✅" if config.GEMINI_KEY else "❌"
        await event.respond(helpers.wm(
            f"**Status AI:**\n{status}\n"
            f"Foto (Gemini): {img_status} `{config.GEMINI_IMG_MODEL}`"
        ))
        await event.delete()