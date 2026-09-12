"""Admin grup: blacklist + ban/unban/kick/promote/demote."""
from telethon import events
from telethon.tl.functions.channels import EditAdminRequest, EditBannedRequest
from telethon.tl.types import ChatBannedRights

from core import helpers, store


def load():
    client = helpers.state.client

    # ---------- BLACKLIST ----------
    @client.on(events.NewMessage(pattern=helpers.cmd("addbl"), outgoing=True))
    async def blacklist_group(event):
        group_id = event.chat_id
        blacklist = store.load("blacklist", [])
        if group_id not in blacklist:
            blacklist.append(group_id)
            store.save("blacklist", blacklist)
            await event.respond(helpers.wm("🚫 Grup ini masuk blacklist broadcast."))
        else:
            await event.respond(helpers.wm("🚫 Grup ini sudah di blacklist."))
        await event.delete()

    @client.on(events.NewMessage(pattern=helpers.cmd("unbl"), outgoing=True))
    async def unblacklist_group(event):
        group_id = event.chat_id
        blacklist = store.load("blacklist", [])
        if group_id in blacklist:
            blacklist.remove(group_id)
            store.save("blacklist", blacklist)
            await event.respond(helpers.wm("✅ Grup dihapus dari blacklist."))
        else:
            await event.respond(helpers.wm("ℹ️ Grup ini tidak ada di blacklist."))
        await event.delete()

    @client.on(events.NewMessage(pattern=helpers.cmd("showbl"), outgoing=True))
    async def show_blacklist(event):
        blacklist = store.load("blacklist", [])
        if not blacklist:
            await event.respond(helpers.wm("📭 Blacklist kosong."))
            await event.delete()
            return
        lines = []
        for gid in blacklist:
            try:
                entity = await client.get_entity(gid)
                name = getattr(entity, "title", None) or getattr(entity, "username", None) or str(gid)
                lines.append(f"{name} (`{gid}`)")
            except Exception:
                lines.append(f"`{gid}` (error)")
        await event.respond(helpers.wm("🔴 **Blacklist Groups:**\n" + "\n".join(lines)))
        await event.delete()

    # ---------- ADMIN ACTIONS ----------
    @client.on(events.NewMessage(pattern=helpers.cmd("ban"), outgoing=True))
    async def ban(event):
        reply = await event.get_reply_message()
        if not reply or not reply.sender:
            await event.respond(helpers.wm("❌ Reply ke pesan user yang mau di-ban."))
            await event.delete()
            return
        uid = reply.sender_id
        try:
            rights = ChatBannedRights(until_date=None, view_messages=True)
            await client(EditBannedRequest(event.chat_id, uid, rights))
            await event.respond(helpers.wm(f"🔨 Banned `{uid}`"))
        except Exception as e:
            await event.respond(helpers.wm(f"❌ Gagal ban: {e}"))
        await event.delete()

    @client.on(events.NewMessage(pattern=helpers.cmd("unban"), outgoing=True))
    async def unban(event):
        reply = await event.get_reply_message()
        if not reply or not reply.sender:
            await event.respond(helpers.wm("❌ Reply ke pesan user yang mau di-unban."))
            await event.delete()
            return
        uid = reply.sender_id
        try:
            rights = ChatBannedRights()
            await client(EditBannedRequest(event.chat_id, uid, rights))
            await event.respond(helpers.wm(f"✅ Unbanned `{uid}`"))
        except Exception as e:
            await event.respond(helpers.wm(f"❌ Gagal unban: {e}"))
        await event.delete()

    @client.on(events.NewMessage(pattern=helpers.cmd("kick"), outgoing=True))
    async def kick(event):
        reply = await event.get_reply_message()
        if not reply or not reply.sender:
            await event.respond(helpers.wm("❌ Reply ke pesan user yang mau di-kick."))
            await event.delete()
            return
        uid = reply.sender_id
        try:
            rights = ChatBannedRights(until_date=None, view_messages=True)
            await client(EditBannedRequest(event.chat_id, uid, rights))
            rights = ChatBannedRights()
            await client(EditBannedRequest(event.chat_id, uid, rights))
            await event.respond(helpers.wm(f"🦵 Kicked `{uid}`"))
        except Exception as e:
            await event.respond(helpers.wm(f"❌ Gagal kick: {e}"))
        await event.delete()

    @client.on(events.NewMessage(pattern=helpers.cmd("promote"), outgoing=True))
    async def promote(event):
        reply = await event.get_reply_message()
        if not reply or not reply.sender:
            await event.respond(helpers.wm("❌ Reply ke pesan user yang mau di-promote."))
            await event.delete()
            return
        uid = reply.sender_id
        try:
            from telethon.tl.types import ChatAdminRights
            rights = ChatAdminRights(delete_messages=True, ban_users=True, invite_users=True, change_info=True, pin_messages=True, manage_call=True)
            await client(EditAdminRequest(event.chat_id, uid, rights, rank="admin"))
            await event.respond(helpers.wm(f"👑 Promoted `{uid}`"))
        except Exception as e:
            await event.respond(helpers.wm(f"❌ Gagal promote: {e}"))
        await event.delete()

    @client.on(events.NewMessage(pattern=helpers.cmd("demote"), outgoing=True))
    async def demote(event):
        reply = await event.get_reply_message()
        if not reply or not reply.sender:
            await event.respond(helpers.wm("❌ Reply ke pesan user yang mau di-demote."))
            await event.delete()
            return
        uid = reply.sender_id
        try:
            from telethon.tl.types import ChatAdminRights
            rights = ChatAdminRights()
            await client(EditAdminRequest(event.chat_id, uid, rights, rank=""))
            await event.respond(helpers.wm(f"⬇️ Demoted `{uid}`"))
        except Exception as e:
            await event.respond(helpers.wm(f"❌ Gagal demote: {e}"))
        await event.delete()