"""Media: QR codes, auto-save media, anti-delete, downloader yt-dlp."""
import asyncio
import os
from datetime import datetime
from pathlib import Path

from telethon import events

from core import helpers, store
from core.state import state

QR_DIR = Path("qr_codes")
MEDIA_DIR = Path("saved")
DL_DIR = Path("downloads")
QR_DIR.mkdir(exist_ok=True)
MEDIA_DIR.mkdir(exist_ok=True)
DL_DIR.mkdir(exist_ok=True)

SAVED_KEY = "saved_chats"
AI_DELETE = "setting_antidel"

_antidel_buffer = {}  # chat_id -> {msg_id: Message}


def _saved_chats():
    return store.load(SAVED_KEY, [])


def _antidel_enabled():
    return bool(store.load(AI_DELETE, False))


def load():
    client = state.client

    # ---------- QR ----------
    @client.on(events.NewMessage(pattern=helpers.cmd("addqr"), outgoing=True))
    async def add_qr(event):
        reply = await event.get_reply_message()
        if not reply or not reply.media:
            await helpers.temp(event, helpers.wm("❌ Reply ke foto QR."))
            await event.delete()
            return
        try:
            ts = datetime.now().strftime("%Y%m%d%H%M%S")
            path = QR_DIR / f"qr_{ts}.jpg"
            await client.download_media(reply, file=str(path))
            await helpers.temp(event, helpers.wm("✅ QR disimpan."))
        except Exception:
            await helpers.temp(event, helpers.wm("❌ Gagal simpan QR."))
        await event.delete()

    @client.on(events.NewMessage(pattern=helpers.cmd("getqr"), outgoing=True))
    async def get_qr(event):
        files = sorted(QR_DIR.glob("*.jpg"))
        if not files:
            await helpers.temp(event, helpers.wm("📭 Belum ada QR."))
            await event.delete()
            return
        for f in files[:10]:
            try:
                await client.send_file(event.chat_id, str(f), caption=helpers.wm(f"🖼 QR: {f.name}"))
                await asyncio.sleep(1)
            except Exception:
                break
        await event.delete()

    @client.on(events.NewMessage(pattern=helpers.cmd("delqr", r"\s+(\d+)"), outgoing=True))
    async def del_qr(event):
        idx = int(event.pattern_match.group(1))
        files = sorted(QR_DIR.glob("*.jpg"))
        if 0 <= idx < len(files):
            try:
                files[idx].unlink()
                await helpers.temp(event, helpers.wm("🗑 QR dihapus."))
            except Exception:
                await helpers.temp(event, helpers.wm("❌ Gagal hapus QR."))
        else:
            await helpers.temp(event, helpers.wm("❌ Index tidak ada."))

    # ---------- SAVE (manual) ----------
    @client.on(events.NewMessage(pattern=helpers.cmd("save"), outgoing=True))
    async def save_media(event):
        reply = await event.get_reply_message()
        if not reply or not reply.media:
            await helpers.temp(event, helpers.wm("❌ Reply ke media yang mau disimpan."))
            await event.delete()
            return
        try:
            await client.forward_messages("me", reply.id, reply.chat_id)
            await helpers.temp(event, helpers.wm("✅ Media disimpan ke Saved Messages."))
        except Exception:
            await helpers.temp(event, helpers.wm("❌ Gagal simpan media."))
        await event.delete()

    # ---------- AUTO-SAVE MEDIA ----------
    @client.on(events.NewMessage(pattern=helpers.cmd("savetoggle"), outgoing=True))
    async def save_toggle(event):
        chats = _saved_chats()
        cid = int(event.chat_id)
        if cid in chats:
            chats.remove(cid)
            txt = "⛔ Auto-save media grup ini dimatikan."
        else:
            chats.append(cid)
            txt = "✅ Auto-save media grup ini dinyalakan."
        store.save(SAVED_KEY, chats)
        await helpers.temp(event, helpers.wm(txt))
        await event.delete()

    @client.on(events.NewMessage(pattern=helpers.cmd("savelist"), outgoing=True))
    async def save_list(event):
        chats = _saved_chats()
        if not chats:
            await event.respond(helpers.wm("📭 Tidak ada grup auto-save."))
            return
        lines = []
        for cid in chats:
            try:
                ent = await client.get_entity(int(cid))
                lines.append(getattr(ent, "title", None) or str(cid))
            except Exception:
                lines.append(str(cid))
        await event.respond(helpers.wm("**Auto-Save Media:**\n" + "\n".join(lines)))

    @client.on(events.NewMessage(incoming=True))
    async def auto_save(event):
        if event.message.out:
            return
        if int(event.chat_id) not in _saved_chats():
            return
        if not event.message.media:
            return
        try:
            folder = MEDIA_DIR / str(event.chat_id)
            folder.mkdir(parents=True, exist_ok=True)
            await client.download_media(event.message, file=str(folder))
        except Exception:
            pass

    # ---------- ANTI-DELETE ----------
    @client.on(events.NewMessage(pattern=helpers.cmd("antidel"), outgoing=True))
    async def antidel(event):
        args = event.message.message.split(None, 1)
        state_val = args[1].strip().lower() if len(args) > 1 else "on"
        enabled = state_val in ("on", "1", "true", "yes")
        store.save(AI_DELETE, enabled)
        await helpers.temp(event, helpers.wm("🛡️ Anti-delete ON - pesan yang dihapus akan disimpan." if enabled else "❌ Anti-delete dimatikan."))
        await event.delete()

    @client.on(events.NewMessage(incoming=True))
    async def buffer_messages(event):
        if not _antidel_enabled():
            return
        buf = _antidel_buffer.setdefault(int(event.chat_id), {})
        buf[event.message.id] = event.message
        if len(buf) > 100:
            oldest = min(buf.keys())
            buf.pop(oldest, None)

    @client.on(events.MessageDeleted)
    async def on_delete(event):
        if not _antidel_enabled():
            return
        chat_id = getattr(event, "chat_id", None)
        if chat_id is None:
            return
        buf = _antidel_buffer.get(int(chat_id), {})
        for mid in event.deleted_ids:
            msg = buf.pop(mid, None)
            if msg is None:
                continue
            try:
                await client.send_message(
                    "me",
                    f"🗑 Pesan dihapus dari group/chat ini.\n\n" + (msg.text or "(media)"),
                )
                if msg.media:
                    await client.forward_messages("me", msg.id, msg.chat_id)
            except Exception:
                pass

    # ---------- DOWNLOADER (yt-dlp, opsional) ----------
    async def download_url(url, chat_id, audio=False):
        try:
            import yt_dlp
        except ImportError:
            await client.send_message(chat_id, helpers.wm("❌ yt-dlp belum terpasang. Install: `pip install yt-dlp`"))
            return

        def _do_download():
            ydl_opts = {
                "outtmpl": str(DL_DIR / "%(title)s.%(ext)s"),
                "quiet": True,
                "noplaylist": True,
            }
            if audio:
                ydl_opts.update({"format": "bestaudio", "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]})
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                return ydl.prepare_filename(info)

        try:
            path = await asyncio.to_thread(_do_download)
            if audio:
                path = os.path.splitext(path)[0] + ".mp3"
            await client.send_file(chat_id, path, caption=helpers.wm("📥 Download selesai."))
            if os.path.exists(path):
                os.remove(path)
        except Exception as e:
            await client.send_message(chat_id, helpers.wm(f"❌ Gagal download: {e}"))

    @client.on(events.NewMessage(pattern=helpers.cmd("dl", r"\s+"), outgoing=True))
    async def dl(event):
        url = event.message.message.split(None, 1)[1].strip()
        await event.respond(helpers.wm("📥 Mendownload..."))
        await download_url(url, event.chat_id, audio=False)
        await event.delete()

    @client.on(events.NewMessage(pattern=helpers.cmd("dla", r"\s+"), outgoing=True))
    async def dla(event):
        url = event.message.message.split(None, 1)[1].strip()
        await event.respond(helpers.wm("🎵 Mengunduh audio..."))
        await download_url(url, event.chat_id, audio=True)
        await event.delete()