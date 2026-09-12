"""Automasi: AFK, auto-reply filter, auto-forward, pengingat."""
import asyncio

from telethon import events

from core import helpers, state, store

FILTERS_KEY = "filters"
FORWARDS_KEY = "forwards"

_afk_reason = None


def load():
    client = state.client

    # ---------- AFK ----------
    @client.on(events.NewMessage(pattern=helpers.cmd("afk"), outgoing=True))
    async def afk(event):
        global _afk_reason
        text = event.message.message.split(None, 1)
        _afk_reason = text[1].strip() if len(text) > 1 else "AFK"
        await event.respond(helpers.wm(f"💤 AFK aktif: {_afk_reason}"))
        await event.delete()

    @client.on(events.NewMessage(pattern=helpers.cmd("back"), outgoing=True))
    async def back(event):
        global _afk_reason
        _afk_reason = None
        await event.respond(helpers.wm("👋 Balik lagi."))
        await event.delete()

    @client.on(events.NewMessage(incoming=True))
    async def handle_incoming(event):
        global _afk_reason
        if not _afk_reason:
            return
        if event.message.out:
            return
        if event.mentioned or (event.is_private and not event.is_group):
            await event.reply(helpers.wm(f"🤖 Lagi AFK. Alasan: {_afk_reason}"))

    # ---------- AUTO-REPLY FILTER ----------
    @client.on(events.NewMessage(pattern=helpers.cmd("filter", r"\s+add\s+"), outgoing=True))
    async def filter_add(event):
        text = event.message.message.split(None, 3)
        if len(text) < 4:
            await event.respond(helpers.wm("❌ Pakai: `.filter add <kata> <balasan>`"))
            return
        keyword = text[2]
        reply = text[3]
        filters = store.load(FILTERS_KEY, [])
        filters.append({"kw": keyword.lower(), "reply": reply})
        store.save(FILTERS_KEY, filters)
        await event.respond(helpers.wm(f"✅ Filter `{keyword}` ditambahkan."))
        await event.delete()

    @client.on(events.NewMessage(pattern=helpers.cmd("filter", r"\s+list"), outgoing=True))
    async def filter_list(event):
        filters = store.load(FILTERS_KEY, [])
        if not filters:
            await event.respond(helpers.wm("📭 Tidak ada filter."))
            return
        lines = [f"`#{i}` **{f['kw']}** -> {f['reply']}" for i, f in enumerate(filters)]
        await event.respond(helpers.wm("**Auto-Replay Filter:**\n" + "\n".join(lines)))

    @client.on(events.NewMessage(pattern=helpers.cmd("filter", r"\s+del\s+(\d+)"), outgoing=True))
    async def filter_del(event):
        idx = int(event.pattern_match.group(1))
        filters = store.load(FILTERS_KEY, [])
        if 0 <= idx < len(filters):
            removed = filters.pop(idx)
            store.save(FILTERS_KEY, filters)
            await event.respond(helpers.wm(f"🗑 Filter `{removed['kw']}` dihapus."))
        else:
            await event.respond(helpers.wm("❌ Index tidak ada."))

    @client.on(events.NewMessage(incoming=True))
    async def auto_reply(event):
        if not event.message.text:
            return
        if event.message.out:
            return
        filters = store.load(FILTERS_KEY, [])
        if not filters:
            return
        low = event.message.text.lower()
        for f in filters:
            if f["kw"] in low:
                try:
                    await event.reply(helpers.wm(f["reply"]))
                    state.stats["auto_reply_sent"] += 1
                    if event.chat_id and event.chat_id != event.sender_id:
                        break
                except Exception:
                    pass
                break

    # ---------- AUTO-FORWARD ----------
    @client.on(events.NewMessage(pattern=helpers.cmd("fwd"), outgoing=True))
    async def fwd(event):
        args = event.message.message.split(None, 1)
        if len(args) < 2:
            await event.respond(helpers.wm("❌ Pakai: `.fwd <username/ID target>`"))
            return
        try:
            target = await client.get_input_entity(args[1].strip().lstrip("@"))
            forwards = store.load(FORWARDS_KEY, {})
            forwards[str(event.chat_id)] = int(getattr(target, "user_id", target))
            store.save(FORWARDS_KEY, forwards)
            await event.respond(helpers.wm("✅ Semua pesan dari grup ini akan diteruskan."))
        except Exception as e:
            await event.respond(helpers.wm(f"❌ Gagal: {e}"))
        await event.delete()

    @client.on(events.NewMessage(pattern=helpers.cmd("fwdlist"), outgoing=True))
    async def fwd_list(event):
        forwards = store.load(FORWARDS_KEY, {})
        if not forwards:
            await event.respond(helpers.wm("📭 Tidak ada auto-forward aktif."))
            return
        lines = []
        for src, dst in forwards.items():
            try:
                src_name = getattr(await client.get_entity(int(src)), "title", src)
            except Exception:
                src_name = src
            lines.append(f"`{src}` ({src_name}) -> `{dst}`")
        await event.respond(helpers.wm("**Auto-Forward:**\n" + "\n".join(lines)))

    @client.on(events.NewMessage(pattern=helpers.cmd("fwdstop"), outgoing=True))
    async def fwd_stop(event):
        forwards = store.load(FORWARDS_KEY, {})
        key = str(event.chat_id)
        if key in forwards:
            del forwards[key]
            store.save(FORWARDS_KEY, forwards)
            await event.respond(helpers.wm("⛔ Auto-forward grup ini dihentikan."))
        else:
            await event.respond(helpers.wm("ℹ️ Grup ini tidak punya auto-forward."))
        await event.delete()

    @client.on(events.NewMessage(incoming=True))
    async def do_forward(event):
        if event.message.out:
            return
        forwards = store.load(FORWARDS_KEY, {})
        src = str(event.chat_id)
        if src not in forwards:
            return
        try:
            await client.forward_messages(forwards[src], event.message.id, event.chat_id)
        except Exception:
            pass

    # ---------- REMINDER ----------
    @client.on(events.NewMessage(pattern=helpers.cmd("remind", r"\s+(\d+)\s+"), outgoing=True))
    async def remind(event):
        seconds = int(event.pattern_match.group(1))
        text = event.message.message.split(None, 2)
        reminder = text[2] if len(text) > 2 else "Pengingat!"
        if seconds <= 0 or seconds > 86400:
            await event.respond(helpers.wm("❌ Detik harus 1-86400."))
            return
        await event.respond(helpers.wm(f"⏰ Diingatkan dalam {seconds} detik."))
        await event.delete()

        async def do_remind():
            await asyncio.sleep(seconds)
            try:
                await client.send_message(event.chat_id, helpers.wm(f"⏰ **Pengingat:** {reminder}"))
            except Exception:
                pass

        asyncio.ensure_future(do_remind())