"""AI backend: opencode (default) atau Gemini. Aktifkan dengan set GEMINI_KEY di .env."""
import asyncio
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

    @client.on(events.NewMessage(pattern=helpers.cmd("ailist"), outgoing=True))
    async def ailist(event):
        provider = _provider()
        status = "❌ Nonaktif — set GEMINI_KEY di .env" if not provider else \
            f"✅ Aktif\nProvider: `{provider}`\nModel: `{_model()}`"
        await event.respond(helpers.wm(f"**Status AI:**\n{status}"))
        await event.delete()