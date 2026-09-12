"""AI Gemini (opsional). Aktifkan dengan set GEMINI_KEY di .env."""
import asyncio
import json
import urllib.request

from telethon import events

from core import config, helpers, state


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


def chunks(text, size=4000):
    return [text[i:i + size] for i in range(0, len(text), size)] if text else ["(kosong)"]


def load():
    client = state.client

    @client.on(events.NewMessage(pattern=helpers.cmd("ai", r"\s+"), outgoing=True))
    async def ai(event):
        if not config.GEMINI_KEY:
            await event.respond(helpers.wm("❌ GEMINI_KEY belum diatur di .env"))
            await event.delete()
            return
        question = event.message.message.split(None, 1)[1].strip()
        reply = await event.get_reply_message()
        context = reply.message if reply else ""
        note = await event.respond(helpers.wm("🤔 Memproses..."))
        answer = await ask_gemini(question, context)
        try:
            await note.delete()
        except Exception:
            pass
        for part in chunks(answer):
            await event.respond(helpers.wm(part))
        await event.delete()

    @client.on(events.NewMessage(pattern=helpers.cmd("ailist"), outgoing=True))
    async def ailist(event):
        status = "✅ Aktif" if config.GEMINI_KEY else "❌ Nonaktif — set GEMINI_KEY di .env"
        await event.respond(helpers.wm(f"**Status AI:**\nModel: `{config.GEMINI_MODEL}`\n{status}"))
        await event.delete()