"""Log detail: rekam SEMUA pesan masuk/keluar dan event userbot.

- Recorder global menangkap tiap pesan (masuk/keluar) + command yg dijalankan.
- `.log [n]` lihat log terbaru.
- `.logfilter <level>` lihat log per level.
- `.logclear` hapus semua log.
"""
from datetime import datetime

from telethon import events

from core import helpers, logger
from core.state import state

MAX_CHARS = 100


def _ts(ts):
    return datetime.fromtimestamp(ts).strftime("%d/%m %H:%M:%S")


def _msg_text(e):
    try:
        if e.message and e.message.message:
            return e.message.message
        if getattr(e, "media", None):
            return f"[media: {e.media.__class__.__name__}]"
        if e.message and e.message.sticker:
            return "[stiker]"
    except Exception:
        pass
    return ""


def _chat_name(e):
    try:
        if getattr(e, "chat", None):
            return getattr(e.chat, "title", None) or getattr(e.chat, "username", None) or str(e.chat_id)
        return str(e.chat_id)
    except Exception:
        return str(e.chat_id)


def _sender_name(e):
    try:
        s = getattr(e, "sender", None)
        if s:
            return getattr(s, "first_name", None) or getattr(s, "username", None) or str(e.sender_id)
        return str(e.sender_id)
    except Exception:
        return str(getattr(e, "sender_id", "?"))


async def _record_event(e):
    text = _msg_text(e)
    if not text and not getattr(e, "media", None):
        return
    if e.out:
        level = "CMD" if (text or "").startswith(helpers.PREFIX) else "OUT"
    else:
        level = "IN"
    detail = f"chat={_chat_name(e)} | dari={_sender_name(e)}"
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + "…"
    logger.record(level, text, detail)


def load():
    client = state.client

    @client.on(events.NewMessage())
    async def global_recorder(e):
        try:
            await _record_event(e)
        except Exception:
            pass

    @client.on(events.NewMessage(pattern=helpers.cmd("log", r"(?:\s+\d+)?\s*$"), outgoing=True))
    async def show_log(event):
        raw = (event.message.message or "").strip()
        parts = raw.split()
        n = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 20
        n = max(1, min(n, 100))
        entries = logger.recent(n)
        if not entries:
            await helpers.temp(event, helpers.wm("📭 Belum ada log."))
            await event.delete()
            return
        lines = [f"**📜 LOG TERBARU ({len(entries)})**\n"]
        for e in entries:
            lines.append(f"`{_ts(e['t'])}` **[{e['level']}]** {e['text']}")
        lines.append(f"\nTotal tersimpan: `{logger.stats()['total']}`")
        await event.respond(helpers.wm("\n".join(lines)))
        await event.delete()

    @client.on(events.NewMessage(pattern=helpers.cmd("logfilter", r"\s+(\S+)"), outgoing=True))
    async def filter_log(event):
        level = event.pattern_match.group(1).upper()
        entries = logger.recent(50, level=level)
        if not entries:
            await helpers.temp(event, helpers.wm(f"📭 Tidak ada log level `{level}`."))
            await event.delete()
            return
        lines = [f"**🔎 LOG LEVEL {level} ({len(entries)})**\n"]
        for e in entries:
            extra = f"\n  └ {e['detail']}" if e.get("detail") else ""
            lines.append(f"`{_ts(e['t'])}` {e['text']}{extra}")
        await event.respond(helpers.wm("\n".join(lines)))
        await event.delete()

    @client.on(events.NewMessage(pattern=helpers.cmd("logclear"), outgoing=True))
    async def clear_log(event):
        logger.clear()
        await helpers.temp(event, helpers.wm("🗑 Semua log dihapus."))
        await event.delete()