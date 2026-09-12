"""Promo & broadcast: gcast, gcast terjadwal, template, jgc (auto-join), spam, deteksi link."""
import asyncio
import os
import random
import re

from telethon import events
from telethon.errors import FloodWaitError
from telethon.tl.functions.messages import ImportChatInviteRequest

from core import config, helpers, inline, notify, state, store

os.makedirs("downloads", exist_ok=True)

VARIANTS_KEY = "variants"


def _load_variants():
    saved = store.load(VARIANTS_KEY, None)
    if saved:
        return saved
    merged = list(config.VARIANTS)
    store.save(VARIANTS_KEY, merged)
    return merged


def _save_variants(variants):
    store.save(VARIANTS_KEY, variants)


def _is_group_dialog(dialog):
    try:
        return dialog.is_group
    except Exception:
        return False


async def _poke(peer, text):
    try:
        await state.client.send_message(peer, text)
    except Exception:
        pass


async def _media_for_reply(reply_msg, chat_id):
    """Return (file_path|cached_file_id, caption) untuk pesan reply ber-media."""
    if not reply_msg or not reply_msg.media:
        return None, None
    try:
        path = await state.client.download_media(reply_msg, file=os.path.join("downloads", "gcast_media"))
        return path, reply_msg.message
    except Exception:
        return None, None


async def _broadcast(chat_id, text, media_path, status_id=None):
    """Send ke semua grup, tanpa melewati blacklist. Return jumlah terkirim."""
    client = state.client
    sender = chat_id

    async def update_status(sent, total, note=""):
        if status_id is None:
            return
        bar = helpers.progress_bar(sent, total)
        txt = f"📣 **Broadcast in progress**\n`{bar}` {sent}/{total}\n{note}"
        try:
            await client.edit_message(sender, status_id, txt)
        except Exception:
            pass

    try:
        dialogs = await client.get_dialogs()
    except Exception as e:
        await _poke(sender, f"❌ Gagal ambil daftar grup: {e}")
        return 0

    groups = [d for d in dialogs if _is_group_dialog(d)]
    blacklist = store.load("blacklist", [])

    sent = 0
    failed = 0
    try:
        total = len(groups)
        for i, dialog in enumerate(groups):
            if state.stop.get("gcast"):
                await _poke(sender, "⛔ Broadcast dihentikan.")
                break
            if dialog.id in blacklist:
                continue
            try:
                await state.flood.wait(
                    "send", config.SEND_RATE, config.SEND_WINDOW,
                    peer=dialog.id, peer_interval=config.GROUP_SEND_INTERVAL,
                )
                if not media_path:
                    await client.send_message(dialog.id, text)
                else:
                    await client.send_file(dialog.id, media_path, caption=text)
                sent += 1
            except FloodWaitError as e:
                await state.flood.on_flood(e.seconds)
            except Exception:
                failed += 1
            if (i + 1) % 10 == 0 or i == total - 1:
                await update_status(sent + failed, total, f"🚫 {failed} gagal | ✉️ {sent} ok")
    finally:
        state.stop["gcast"] = False

    state.stats["gcast_sent"] += sent
    notify.log(f"Gcast selesai: {sent} grup dikirim, {failed} gagal.", "INFO")
    return sent, failed


async def _join_all(chat_id, status_id=None):
    client = state.client
    links = list(state.detected_links)

    async def update_status(joined, total, note=""):
        if status_id is None:
            return
        bar = helpers.progress_bar(joined, total)
        try:
            await client.edit_message(chat_id, status_id, f"🚀 **Auto-join**\n`{bar}` {joined}/{total}\n{note}")
        except Exception:
            pass

    if not links:
        await _poke(chat_id, "❌ Tidak ada link grup yang terdeteksi.")
        return

    await update_status(0, len(links))

    joined = 0
    failed = 0
    try:
        for idx, link in enumerate(links):
            if state.stop.get("jgc"):
                await _poke(chat_id, "⛔ Auto-join dihentikan.")
                break
            delay = random.uniform(config.JOIN_DELAY_MIN, config.JOIN_DELAY_MAX)
            try:
                await state.flood.wait(
                    "join", config.JOIN_LIMIT, config.JOIN_WINDOW,
                    peer=link, peer_interval=delay,
                )
                invite_hash = link.split("+")[-1]
                await client(ImportChatInviteRequest(invite_hash))
                joined += 1
                await update_status(joined + failed, len(links), f"✅ {joined} join")
            except FloodWaitError as e:
                await state.flood.on_flood(e.seconds)
            except Exception:
                failed += 1
                await update_status(joined + failed, len(links), f"❌ {failed} gagal")
            if (idx + 1) % 5 == 0 or idx == len(links) - 1:
                await update_status(joined + failed, len(links), f"✅ {joined} join | ❌ {failed} gagal")
    finally:
        state.stop["jgc"] = False
        state.detected_links.clear()

    report = f"✅ Berhasil join: {joined} grup.\n❌ Gagal: {failed} grup."
    await _poke(chat_id, report)


def load():
    client = state.client

    @client.on(events.NewMessage(incoming=True))
    async def detect_links(event):
        if event.message.text:
            pattern = r"https://t\.me/\+[\w-]+"
            for link in re.findall(pattern, event.message.text):
                state.detected_links.add(link)

    @client.on(events.NewMessage(pattern=helpers.cmd("gcast"), outgoing=True))
    async def gcast(event):
        reply = await event.get_reply_message()
        if not reply:
            await event.respond(helpers.wm("❌ Reply ke pesan yang mau di-broadcast."))
            await event.delete()
            return
        if state.stop.get("gcast"):
            await event.respond(helpers.wm("⛔ Ada broadcast berjalan. Tunggu atau .stopcast."))
            return

        await event.delete()
        status = await event.respond(helpers.wm("📣 **Broadcast dimulai...**"))
        await inline.send_stop_panel(event.chat_id, "gcast")
        media_path, caption = await _media_for_reply(reply, event.chat_id)
        text = caption or (reply.message or "")
        sent, failed = await _broadcast(event.chat_id, text, media_path, status.id)
        await _poke(event.chat_id, f"⚡ Broadcast selesai: {sent} grup terkirim, {failed} gagal.")

    @client.on(events.NewMessage(pattern=helpers.cmd("gcastt"), outgoing=True))
    async def gcast_template(event):
        variants = _load_variants()
        if not variants:
            await event.respond(helpers.wm("❌ Belum ada template promo. Pakai `.addv <teks>` atau set VARIANTS di .env."))
            await event.delete()
            return
        text = random.choice(variants)
        await event.delete()
        status = await event.respond(helpers.wm("📣 **Broadcast template...**"))
        await inline.send_stop_panel(event.chat_id, "gcast")
        sent, failed = await _broadcast(event.chat_id, text, None, status.id)
        await _poke(event.chat_id, f"⚡ Broadcast template selesai: {sent} grup, {failed} gagal.")

    @client.on(events.NewMessage(pattern=helpers.cmd("gcasts", r"\s+(\d+)"), outgoing=True))
    async def gcast_schedule(event):
        minutes = int(event.pattern_match.group(1))
        reply = await event.get_reply_message()
        if not reply:
            await event.respond(helpers.wm("❌ Reply ke pesan yang mau di-broadcast."))
            await event.delete()
            return
        content = reply.message or ""
        await event.respond(helpers.wm(f"⏳ Broadcast terjadwal dalam {minutes} menit.\nKetuk .stopcast untuk batal."))
        await event.delete()

        async def scheduled():
            await asyncio.sleep(minutes * 60)
            media_path, caption = await _media_for_reply(reply, event.chat_id)
            text = caption or content
            status = await state.client.send_message(event.chat_id, helpers.wm("📣 **Broadcast terjadwal dimulai...**"))
            sent, failed = await _broadcast(event.chat_id, text, media_path, status.id)
            await _poke(event.chat_id, f"⚡ Broadcast terjadwal selesai: {sent} grup, {failed} gagal.")

        asyncio.ensure_future(scheduled())

    @client.on(events.NewMessage(pattern=helpers.cmd("addv"), outgoing=True))
    async def add_variant(event):
        text = event.message.message.split(None, 1)
        if len(text) < 2:
            await event.respond(helpers.wm("❌ Pakai: `.addv <teks promo>`"))
            return
        variants = _load_variants()
        variants.append(text[1])
        _save_variants(variants)
        await event.respond(helpers.wm(f"✅ Template #{len(variants)-1} ditambahkan."))
        await event.delete()

    @client.on(events.NewMessage(pattern=helpers.cmd("delv", r"\s+(\d+)"), outgoing=True))
    async def del_variant(event):
        idx = int(event.pattern_match.group(1))
        variants = _load_variants()
        if 0 <= idx < len(variants):
            removed = variants.pop(idx)
            _save_variants(variants)
            await event.respond(helpers.wm(f"🗑 Template #{idx} dihapus: {removed}"))
        else:
            await event.respond(helpers.wm("❌ Index tidak ada."))

    @client.on(events.NewMessage(pattern=helpers.cmd("listv"), outgoing=True))
    async def list_variants(event):
        variants = _load_variants()
        if not variants:
            await event.respond(helpers.wm("📭 Belum ada template."))
            return
        text = "\n\n".join(f"`#{i}` {v}" for i, v in enumerate(variants))
        await event.respond(helpers.wm(f"**Template Promo:**\n\n{text}"))

    @client.on(events.NewMessage(pattern=helpers.cmd("jgc"), outgoing=True))
    async def join_groups(event):
        if state.stop.get("jgc"):
            await event.respond(helpers.wm("⛔ Ada auto-join berjalan."))
            return
        await event.delete()
        status = await event.respond(helpers.wm("🚀 **Mempersiapkan auto-join...**"))
        await inline.send_stop_panel(event.chat_id, "jgc")
        await _join_all(event.chat_id, status.id)

    @client.on(events.NewMessage(pattern=helpers.cmd("stopcast"), outgoing=True))
    async def stopcast(event):
        stopped = False
        for task in ("gcast", "jgc"):
            if state.stop.get(task):
                task_name = "broadcast" if task == "gcast" else "auto-join"
                await event.respond(helpers.wm(f"⛔ Perintah stop untuk {task_name} dikirim."))
                stopped = True
                break
        if not stopped:
            await event.respond(helpers.wm("ℹ️ Tidak ada proses yang berjalan."))
        state.stop["gcast"] = True
        state.stop["jgc"] = True

    @client.on(events.NewMessage(pattern=helpers.cmd("spam", r"\s+(\d+)"), outgoing=True))
    async def spam(event):
        count = int(event.pattern_match.group(1))
        if count <= 0 or count > 50:
            await event.respond(helpers.wm("❌ Jumlah harus 1-50."))
            await event.delete()
            return
        reply = await event.get_reply_message()
        if not reply:
            await event.respond(helpers.wm("❌ Reply ke pesan yang mau di-spam."))
            await event.delete()
            return
        await event.delete()
        for _ in range(count):
            try:
                await state.flood.wait("send", 20, 60, peer=event.chat_id, peer_interval=1.5)
                if reply.media:
                    path = await client.download_media(reply)
                    await client.send_file(event.chat_id, path, caption=helpers.wm(reply.message))
                else:
                    await client.send_message(event.chat_id, helpers.wm(reply.message))
            except FloodWaitError as e:
                await state.flood.on_flood(e.seconds)
            except Exception:
                break
        await notify.log(f"Spam selesai di chat {event.chat_id} x{count}", "INFO")