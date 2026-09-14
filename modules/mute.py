"""Mute/unmute notifikasi chat: .muteall, .mutegc, .mutepm, .mutechat, dll."""
import asyncio

from telethon import events
from telethon.tl.functions.account import UpdateNotifySettingsRequest
from telethon.tl.types import InputPeerNotifySettings

from core import config, helpers, store
from core.state import state

FOREVER = 2 ** 31 - 1


def _settings(mute):
    return InputPeerNotifySettings(mute_until=FOREVER if mute else 0)


_last_err = None


async def _apply(dialog, mute):
    global _last_err
    try:
        await state.client(UpdateNotifySettingsRequest(
            peer=dialog.input_entity, settings=_settings(mute),
        ))
        return True
    except Exception as e:
        if _last_err != type(e).__name__:
            _last_err = type(e).__name__
            print(f"[MUTE] {type(e).__name__}: {e}")
            try:
                from core import notify
                await notify.log_error(f"mute: {type(e).__name__}: {e}")
            except Exception:
                pass
        return False


def _kind(dialog):
    if dialog.is_group or dialog.is_channel:
        return "gc"
    if dialog.is_user:
        return "pm"
    return "other"


def _count_muted(dialogs):
    return sum(1 for d in dialogs if bool(d.dialog.notify_settings.mute_until))


MEM_KEY = "muted_memory"


def _get_mem():
    mem = store.load(MEM_KEY, {})
    return {k: set(v) for k, v in mem.items()}


def _save_mem(mem):
    store.save(MEM_KEY, {k: sorted(v) for k, v in mem.items()})


def _mem_add(ids, kind):
    mem = _get_mem()
    mem.setdefault(kind, set()).update(str(i) for i in ids)
    _save_mem(mem)
    return mem


def _mem_remove(ids, kind):
    mem = _get_mem()
    bucket = mem.get(kind, set())
    for i in ids:
        bucket.discard(str(i))
    mem[kind] = bucket
    _save_mem(mem)
    return mem


def load():
    client = state.client

    async def _bulk(event, mute, kind):
        state.stop["mute"] = False
        emoji = "🔇" if mute else "🔔"
        verb = "Mute" if mute else "Unmute"
        cooldown = float(event.pattern_match.group(1) or 1.5)
        cooldown = min(max(cooldown, 0.5), 10)

        await event.delete()
        progress = await event.respond(helpers.wm(f"{emoji} {verb} semua chat..."))
        dialogs = await client.get_dialogs()
        if kind != "all":
            dialogs = [d for d in dialogs if _kind(d) == kind]

        mem = _get_mem()
        stored_before = len(mem.get(kind, set()))
        if mute:
            mem_ids = set()
            for bucket in mem.values():
                mem_ids |= bucket
            pending = [d for d in dialogs if str(d.id) not in mem_ids]
            total = len(pending)
            skipped = len(dialogs) - total
        else:
            pending = dialogs
            total = len(pending)
            skipped = 0

        ok = 0
        ids_done = []

        for i, d in enumerate(pending):
            if state.stop.get("mute"):
                await progress.edit(helpers.wm(
                    f"⏹ Dihentikan. Ter-proses: {ok}/{total}"
                ))
                return
            if await _apply(d, mute):
                ok += 1
                ids_done.append(d.id)
            if (i + 1) % 20 == 0 or (i + 1) == total:
                try:
                    await progress.edit(helpers.wm(
                        f"{emoji} Progress: {i+1}/{total} | ✅ {ok}"
                    ))
                except Exception:
                    pass
            if (i + 1) < total:
                await asyncio.sleep(cooldown)

        if mute and ids_done:
            _mem_add(ids_done, kind)
        elif not mute and ids_done:
            _mem_remove(ids_done, kind)

        mem = _get_mem()
        stored = len(mem.get(kind, set()))
        muted = _count_muted(dialogs)
        label = "semua chat" if kind == "all" else ("grup/channel" if kind == "gc" else "chat pribadi")
        extra = f" | ⏭️ Skip memo: {skipped}" if mute and skipped else ""
        await progress.edit(helpers.wm(
            f"{emoji} **{verb} {label} selesai.**\n"
            f"✅ {ok} chat diproses{extra}\n"
            f"🔕 Ter-mute: {muted} | 💾 Memo: {stored}"
        ))

    BASE = r"(?:\s+(\d+))?"

    @client.on(events.NewMessage(pattern=helpers.cmd("muteall", BASE), outgoing=True))
    @client.on(events.NewMessage(pattern=helpers.cmd("mutegc", BASE), outgoing=True))
    @client.on(events.NewMessage(pattern=helpers.cmd("mutepm", BASE), outgoing=True))
    async def bulk_mute(event):
        name = event.message.message.split()[0].lstrip(config.PREFIX)
        kind = {"muteall": "all", "mutegc": "gc", "mutepm": "pm"}.get(name, "all")
        await _bulk(event, True, kind)

    @client.on(events.NewMessage(pattern=helpers.cmd("unmuteall", BASE), outgoing=True))
    @client.on(events.NewMessage(pattern=helpers.cmd("unmutegc", BASE), outgoing=True))
    @client.on(events.NewMessage(pattern=helpers.cmd("unmutepm", BASE), outgoing=True))
    async def bulk_unmute(event):
        name = event.message.message.split()[0].lstrip(config.PREFIX)
        kind = {"unmuteall": "all", "unmutegc": "gc", "unmutepm": "pm"}.get(name, "all")
        await _bulk(event, False, kind)

    @client.on(events.NewMessage(pattern=helpers.cmd("stopmute"), outgoing=True))
    async def stopmute(event):
        state.stop["mute"] = True
        await helpers.temp(event, helpers.wm("⏹ Menghentikan proses mute/unmute..."))
        await event.delete()

    @client.on(events.NewMessage(
        pattern=helpers.cmd("mutechat", r"(?:\s+(\d+))?"), outgoing=True,
    ))
    @client.on(events.NewMessage(
        pattern=helpers.cmd("mute", r"(?:\s+(\d+))?"), outgoing=True,
    ))
    async def mutechat(event):
        hours = float(event.pattern_match.group(1) or 0)
        settings = InputPeerNotifySettings(
            mute_until=int(hours * 3600) or FOREVER
        )
        try:
            await client(UpdateNotifySettingsRequest(
                peer=await client.get_input_entity(event.chat_id),
                settings=settings,
            ))
            kind = "gc" if (event.is_group or event.is_channel) else "pm"
            _mem_add([event.chat_id], kind)
            target = event.chat_id
            ttl = f"{int(hours)} jam" if hours else "selamanya (2038)"
            await helpers.temp(event, helpers.wm(
                f"🔇 Chat `{target}` di-mute {ttl}."
            ))
        except Exception as e:
            await helpers.temp(event, helpers.wm(f"❌ Gagal: {e}"))
        await event.delete()

    @client.on(events.NewMessage(
        pattern=helpers.cmd("unmutechat"), outgoing=True,
    ))
    @client.on(events.NewMessage(
        pattern=helpers.cmd("unmute"), outgoing=True,
    ))
    async def unmutechat(event):
        try:
            await client(UpdateNotifySettingsRequest(
                peer=await client.get_input_entity(event.chat_id),
                settings=_settings(False),
            ))
            kind = "gc" if (event.is_group or event.is_channel) else "pm"
            _mem_remove([event.chat_id], kind)
            await helpers.temp(event, helpers.wm(f"🔔 Chat `{event.chat_id}` di-unmute."))
        except Exception as e:
            await helpers.temp(event, helpers.wm(f"❌ Gagal: {e}"))
        await event.delete()

    @client.on(events.NewMessage(
        pattern=helpers.cmd("mutestat"), outgoing=True,
    ))
    async def mutestat(event):
        dialogs = await client.get_dialogs()
        gc = [d for d in dialogs if _kind(d) == "gc"]
        pm = [d for d in dialogs if _kind(d) == "pm"]
        mem = _get_mem()
        stat = (
            f"**🔕 STATUS MUTE**\n"
            f"-----------------------\n"
            f"👥 Grup/Chat: {len(gc)} | 🔇 {_count_muted(gc)}\n"
            f"👤 Private: {len(pm)} | 🔇 {_count_muted(pm)}\n"
            f"💾 Memo GC: `{len(mem.get('gc', set()))}` | Memo PM: `{len(mem.get('pm', set()))}`\n"
            f"📚 Total chat: `{len(dialogs)}`"
        )
        await event.respond(helpers.wm(stat))
        await event.delete()

    @client.on(events.NewMessage(pattern=helpers.cmd("muteflush"), outgoing=True))
    async def muteflush(event):
        store.save(MEM_KEY, {})
        await helpers.temp(event, helpers.wm("🗑 Memori mute dihapus. Semua chat akan diproses lagi di mute berikutnya."))
        await event.delete()