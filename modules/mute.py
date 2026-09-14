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


async def _apply(dialog, mute):
    entity = dialog.entity
    peer = getattr(entity, "input_entity", None)
    if peer is None:
        try:
            peer = await dialog.client.get_input_entity(entity)
        except Exception:
            return False
    try:
        await dialog.client(UpdateNotifySettingsRequest(
            peer=peer, settings=_settings(mute),
        ))
        return True
    except Exception:
        return False


def _kind(dialog):
    if dialog.is_user and not dialog.is_self:
        return "pm"
    if dialog.is_group or dialog.is_channel:
        return "gc"
    return "other"


def _count_muted(dialogs):
    return sum(1 for d in dialogs if bool(d.dialog.notify_settings.mute_until))


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
        total = len(dialogs)
        ok = 0

        for i, d in enumerate(dialogs):
            if state.stop.get("mute"):
                await progress.edit(helpers.wm(
                    f"⏹ Dihentikan. Ter-proses: {ok}/{total}"
                ))
                return
            if await _apply(d, mute):
                ok += 1
            if (i + 1) % 20 == 0 or (i + 1) == total:
                try:
                    await progress.edit(helpers.wm(
                        f"{emoji} Progress: {i+1}/{total} | ✅ {ok}"
                    ))
                except Exception:
                    pass
            if (i + 1) < total:
                await asyncio.sleep(cooldown)

        muted = _count_muted(dialogs)
        label = "semua chat" if kind == "all" else ("grup/channel" if kind == "gc" else "chat pribadi")
        await progress.edit(helpers.wm(
            f"{emoji} **{verb} {label} selesai.**\n"
            f"✅ {ok} chat diproses | 🔕 Ter-mute: {muted}"
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
        stat = (
            f"**🔕 STATUS MUTE**\n"
            f"-----------------------\n"
            f"👥 Grup/Chat: {len(gc)} | 🔇 {_count_muted(gc)}\n"
            f"👤 Private: {len(pm)} | 🔇 {_count_muted(pm)}\n"
            f"📚 Total chat: `{len(dialogs)}`"
        )
        await event.respond(helpers.wm(stat))
        await event.delete()