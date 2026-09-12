"""Panel informasi & bantuan: .ping, .info, .help, .id, .stats."""
import platform
import sys
import time
from datetime import datetime

from telethon import events
from telethon.tl.types import MessageEntityMentionName, User

from core import config, helpers, inline
from core.state import state


async def _uptime():
    if not state.started_at:
        return "?"
    seconds = int(time.time() - state.started_at)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}j {m}m {s}d"


def _sysinfo():
    try:
        import psutil
        mem = psutil.virtual_memory()
        return f"RAM: {mem.percent}% | CPU: {psutil.cpu_percent()}%"
    except Exception:
        return f"OS: {platform.system()} {platform.release()}"


def load():
    client = state.client

    @client.on(events.NewMessage(pattern=helpers.cmd("ping"), outgoing=True))
    async def ping(event):
        start = datetime.now()
        await event.respond(helpers.wm("🏓 Pong!"))
        end = datetime.now()
        latency = (end - start).total_seconds() * 1000
        await event.respond(helpers.wm(f"📈 Latency: {latency:.2f} ms"))
        await event.delete()

    @client.on(events.NewMessage(pattern=helpers.cmd("info"), outgoing=True))
    async def info(event):
        me = await client.get_me()
        try:
            import telethon
            tl = telethon.__version__
        except Exception:
            tl = "?"
        try:
            dialogs = await client.get_dialogs()
            groups = sum(1 for d in dialogs if getattr(d, "is_group", False))
        except Exception:
            groups = "?"
        text = (
            "**🤖 USERBOT INFO**\n"
            "-----------------------\n"
            f"👤 Owner: `{me.first_name}` (`{me.id}`)\n"
            f"⚙️ Versi: `{config.VERSION}`\n"
            f"🐍 Python: `{sys.version.split()[0]}`\n"
            f"📡 Telethon: `{tl}`\n"
            f"⏱ Uptime: `{await _uptime()}`\n"
            f"💾 {_sysinfo()}\n"
            f"👥 Grup: `{groups}`\n"
            f"✨ AI: `{'ON' if config.GEMINI_KEY else 'OFF'}`\n"
            f"🖲 Bot UI: `{'ON' if state.bot else 'OFF'}`"
        )
        await event.respond(helpers.wm(text))
        await event.delete()

    @client.on(events.NewMessage(pattern=helpers.cmd("help"), outgoing=True))
    async def help_cmd(event):
        if await inline.send_menu(event.chat_id):
            await event.delete()
            return
        await event.respond(helpers.wm(inline.build_help_text()))
        await event.delete()

    @client.on(events.NewMessage(pattern=helpers.cmd("stats"), outgoing=True))
    async def stats(event):
        st = state.stats
        text = (
            "**📊 STATISTIK**\n"
            "-----------------------\n"
            f"📣 Pesan broadcast: `{st['gcast_sent']}`\n"
            f"🤖 Auto-reply terkirim: `{st['auto_reply_sent']}`\n"
            f"🔗 Link terdeteksi: `{len(state.detected_links)}`"
        )
        await event.respond(helpers.wm(text))
        await event.delete()

    @client.on(events.NewMessage(pattern=helpers.cmd("id"), outgoing=True))
    async def id_cmd(event):
        if event.is_reply:
            reply = await event.get_reply_message()
            sender = await reply.get_sender()
            user_id = reply.sender_id
            user_name = sender.first_name if isinstance(sender, User) else "?"
        else:
            user_id = event.sender_id
            user_name = "Kamu"
        chat_id = event.chat_id
        chat_text = f"\n💬 Chat ID: `{chat_id}`" if event.is_group else ""
        await event.respond(helpers.wm(f"👤 {user_name} ID: `{user_id}`{chat_text}"))
        await event.delete()