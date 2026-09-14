"""Mute/unmute notifikasi chat: .muteall, .unmuteall, .mutechat, .unmutechat, .mutestat."""
import asyncio

from telethon import events
from telethon.tl.functions.account import UpdateNotifySettingsRequest
from telethon.tl.types import InputPeerNotifySettings

from core import helpers, store
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


def _count_muted(dialogs):
    return sum(1 for d in dialogs if bool(d.dialog.notify_settings.mute_until))


def load():
    client = state.client

    @client.on(events.NewMessage(
        pattern=helpers.cmd("muteall", r"(?:\s+(\d+))?"), outgoing=True,
    ))
    async def muteall(event):
        state.stop["mute"] = False
        cooldown = float(event.pattern_match.group(1) or 1.5)
        cooldown = min(max(cooldown, 0.5), 10)

        await event.delete()
        progress = await event.respond(helpers.wm("🔇 Muting semua chat..."))
        dialogs = await client.get_dialogs()
        total = len(dialogs)
        ok = 0

        for i, d in enumerate(dialogs):
            if state.stop.get("mute"):
                await progress.edit(helpers.wm(
                    f"⏹ Dihentikan. Ter-mute: {ok}/{total}"
                ))
                return
            if await _apply(d, True):
                ok += 1
            if (i + 1) % 20 == 0 or (i + 1) == total:
                try:
                    await progress.edit(helpers.wm(
                        f"🔇 Progress: {i+1}/{total} | ✅ {ok}"
                    ))
                except Exception:
                    pass
            if (i + 1) < total:
                await asyncio.sleep(cooldown)

        muted = _count_muted(dialogs)
        await progress.edit(helpers.wm(
            f"🔇 **Semua chat di-mute.**\n"
            f"✅ {ok} chat diproses | 🔕 Total mute: {muted}"
        ))

    @client.on(events.NewMessage(
        pattern=helpers.cmd("unmuteall", r"(?:\s+(\d+))?"), outgoing=True,
    ))
    async def unmuteall(event):
        state.stop["mute"] = False
        cooldown = float(event.pattern_match.group(1) or 1.5)
        cooldown = min(max(cooldown, 0.5), 10)

        await event.delete()
        progress = await event.respond(helpers.wm("🔔 Unmute semua chat..."))
        dialogs = await client.get_dialogs()
        total = len(dialogs)
        ok = 0

        for i, d in enumerate(dialogs):
            if state.stop.get("mute"):
                await progress.edit(helpers.wm(
                    f"⏹ Dihentikan. Unmute: {ok}/{total}"
                ))
                return
            if await _apply(d, False):
                ok += 1
            if (i + 1) % 20 == 0 or (i + 1) == total:
                try:
                    await progress.edit(helpers.wm(
                        f"🔔 Progress: {i+1}/{total} | ✅ {ok}"
                    ))
                except Exception:
                    pass
            if (i + 1) < total:
                await asyncio.sleep(cooldown)

        muted = _count_muted(dialogs)
        await progress.edit(helpers.wm(
            f"🔔 **Semua chat di-unmute.**\n"
            f"✅ {ok} chat diproses | 🔕 Sisa mute: {muted}"
        ))

    @client.on(events.NewMessage(
        pattern=helpers.cmd("mutechat", r"(?:\s+(\d+))?"), outgoing=True,
    ))
    @client.on(events.NewMessage(
        pattern=helpers.cmd("mute", r"(?:\s+(\d+))?"), outgoing=True,
    ))
    async def mutechat(event):
        hours = float(event.pattern_match.group(1) or 0)
        settings = InputPeerNotifySettings(
            mute_until=int(hours * 3600 // 1) or FOREVER
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
        muted = _count_muted(dialogs)
        await event.respond(helpers.wm(
            f"**🔕 STATUS MUTE**\n"
            f"-----------------------\n"
            f"🔇 Ter-mute: `{muted}`\n"
            f"🔔 Aktif: `{len(dialogs) - muted}`\n"
            f"📚 Total chat: `{len(dialogs)}`"
        ))
        await event.delete()