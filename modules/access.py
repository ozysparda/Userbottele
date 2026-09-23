"""GiveAccess: izinkan orang lain memakai perintah userbot SEMENTARA.

Owner memberi akses via reply / ID / @username + durasi menit. Selama akses
belum habis, user tsb boleh mengetik perintah (prefix default) di PM akun,
dan bot menjalankannya seperti perintah owner sendiri.
"""
import time

from telethon import events

from core import config, helpers, store

ACCESS_KEY = "access"


def _access():
    return store.load(ACCESS_KEY, {})


def _save(data):
    store.save(ACCESS_KEY, data)


def _purge(data):
    now = time.time()
    for uid in [k for k, v in data.items() if v.get("until", 0) <= now]:
        data.pop(uid, None)
    return data


def _fmt_remaining(until):
    s = max(0, int(until - time.time()))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    parts = []
    if h:
        parts.append(f"{h}j")
    if m or h:
        parts.append(f"{m}m")
    parts.append(f"{sec}d")
    return " ".join(parts)


async def _resolve_user(client, target):
    """Resolve target ke user id. Terima: ID angka, @username, atau teks."""
    target = (target or "").strip().lstrip("@")
    if not target:
        return None
    if target.isdigit():
        return int(target)
    try:
        ent = await client.get_input_entity(target)
        uid = getattr(ent, "user_id", None)
        if uid is None and hasattr(ent, "user_id"):
            uid = ent.user_id
        if uid is None:
            full = await client.get_entity(target)
            uid = getattr(full, "id", None)
        return uid
    except Exception:
        return None


def load():
    client = helpers.state.client

    @client.on(events.NewMessage(pattern=helpers.cmd(("giveaccess", "ga"), r"\s+"), outgoing=True))
    async def give_access(event):
        args = event.message.message.split(None, 2)
        target = args[1].strip() if len(args) > 1 else ""
        minutes_txt = args[2].strip() if len(args) > 2 else ""
        reply = await event.get_reply_message()

        if not target and reply and reply.sender_id:
            target = str(reply.sender_id)

        if target.isdigit() and not minutes_txt:
            minutes = int(target)
            target = str(reply.sender_id) if reply and reply.sender_id else ""
            if not target:
                await helpers.temp(event, helpers.wm("❌ Format: `.giveaccess <id|@username> <menit>` (reply juga bisa)."))
                await event.delete()
                return
        else:
            try:
                minutes = int(minutes_txt)
                if minutes <= 0:
                    raise ValueError
            except (ValueError, TypeError):
                await helpers.temp(event, helpers.wm("❌ Format: `.giveaccess <id|@username> <menit>`"))
                await event.delete()
                return

        uid = await _resolve_user(client, target)
        if not uid:
            await helpers.temp(event, helpers.wm("❌ User tidak ditemukan."))
            await event.delete()
            return

        data = _purge(_access())
        data[str(uid)] = {"until": time.time() + minutes * 60, "granted_at": time.time()}
        _save(data)
        try:
            name = getattr(await client.get_entity(uid), "first_name", None) or str(uid)
        except Exception:
            name = str(uid)
        await helpers.temp(event, helpers.wm(
            f"🔓 {name} (`{uid}`) diberi akses selama **{minutes} menit**.\n"
            f"Berakhir dalam: {_fmt_remaining(data[str(uid)]['until'])}"
        ), seconds=6)
        await event.delete()

    @client.on(events.NewMessage(pattern=helpers.cmd(("revokeaccess", "ra"), r"\s+"), outgoing=True))
    async def revoke_access(event):
        target = event.message.message.split(None, 1)[1].strip()
        data = _purge(_access())
        uid = await _resolve_user(client, target)
        if uid and str(uid) in data:
            data.pop(str(uid), None)
            _save(data)
            await helpers.temp(event, helpers.wm(f"🔒 Akses `{uid}` dicabut."))
        else:
            await helpers.temp(event, helpers.wm("ℹ️ User tidak punya akses aktif."))
        await event.delete()

    @client.on(events.NewMessage(pattern=helpers.cmd("accesslist"), outgoing=True))
    async def access_list(event):
        data = _purge(_access())
        _save(data)
        if not data:
            await helpers.temp(event, helpers.wm("📭 Tidak ada yang punya akses aktif."))
            await event.delete()
            return
        lines = []
        for uid, info in sorted(data.items(), key=lambda kv: kv[1]["until"]):
            try:
                ent = await client.get_entity(int(uid))
                name = getattr(ent, "first_name", None) or getattr(ent, "username", None) or str(uid)
            except Exception:
                name = str(uid)
            lines.append(f"`{uid}` {name} — sisa {_fmt_remaining(info['until'])}")
        await event.respond(helpers.wm("🔓 **Daftar akses aktif:**\n" + "\n".join(lines)))
        await event.delete()

    @client.on(events.NewMessage(incoming=True))
    async def relay_granted(event):
        """Perintah dari user berakses (PM) dijalankan sebagai perintah owner."""
        if event.out:
            return
        data = _purge(_access())
        if str(event.sender_id) not in data:
            return
        if not event.is_private:
            return
        text = (event.message.message or "").strip()
        if not text.startswith(config.PREFIX):
            return
        try:
            await event.message.delete()
        except Exception:
            pass
        try:
            await client.send_message(event.chat_id, text)
        except Exception:
            pass