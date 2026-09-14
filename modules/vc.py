"""Voice chat: akun selalu berdiam di VC grup target (.vcstart, .vcstop, .vcstat)."""
import asyncio
import subprocess

from telethon import events

from core import config, helpers, notify
from core.state import state

SILENCE = config.BASE_DIR / "data" / "silence.ogg"

_vc = None
_ready = False
_task = None
_active = {"chat": None}


def _pkgs():
    global _ready
    try:
        from pytgcalls import PyTgCalls
        from pytgcalls.types import GroupCallConfig
        return PyTgCalls, GroupCallConfig
    except Exception as e:
        print(f"[VC] py-tgcalls belum terinstall: {e}")
        _ready = False
        return None, None


def _make_silence():
    if SILENCE.exists() and SILENCE.stat().st_size > 0:
        return True
    SILENCE.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
             "-t", "43200", "-c:a", "libopus", "-b:a", "12k", str(SILENCE)],
            check=True, capture_output=True, timeout=90,
        )
        return SILENCE.exists() and SILENCE.stat().st_size > 0
    except Exception:
        pass
    try:
        import wave
        with wave.open(str(SILENCE), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(1)
            w.setframerate(8000)
            w.writeframes(b"\x80" * (8000 * 180))
        return True
    except Exception:
        return False


async def _resolve_target(event, arg):
    if arg:
        text = arg.strip()
        try:
            ent = await state.client.get_entity(text)
        except Exception as e:
            raise ValueError(f"tidak bisa resolve '{text}': {e}")
        chat_id = int(getattr(ent, "id", 0))
        label = helpers.chat_title(ent) or text
    else:
        chat_id = event.chat_id
        label = "chat ini"
    if chat_id >= 0:
        raise ValueError("target harus grup/channel (bukan user)")
    return chat_id, label


async def _persist():
    if getattr(state, "save_meta", None):
        try:
            await state.save_meta()
        except Exception as e:
            print(f"[VC] gagal simpan meta: {e}")


def _meta_target():
    return (state.bot_meta or {}).get("vc_target")


async def start_vc(chat_id, label=None):
    global _vc, _ready, _task
    PyTgCalls, GroupCallConfig = _pkgs()
    if PyTgCalls is None:
        raise RuntimeError("py-tgcalls tidak tersedia")
    state.stop["vc"] = False
    if not await asyncio.to_thread(_make_silence):
        raise RuntimeError("gagal membuat file silence")
    if _vc is None:
        _vc = PyTgCalls(state.client)
        await _vc.start()
        _ready = True
    await _vc.play(chat_id, str(SILENCE), GroupCallConfig(auto_start=True))
    try:
        await _vc.mute(chat_id)
    except Exception:
        pass
    _active["chat"] = chat_id
    if _task is None or _task.done():
        _task = asyncio.create_task(_keepalive(chat_id))
    if label:
        print(f"[VC] masuk VC {chat_id} ({label})")


async def _keepalive(chat_id):
    while not state.stop["vc"]:
        await asyncio.sleep(120)
        try:
            _, GroupCallConfig = _pkgs()
            if _vc is None or GroupCallConfig is None:
                continue
            await _vc.play(chat_id, str(SILENCE), GroupCallConfig(auto_start=True))
            try:
                await _vc.mute(chat_id)
            except Exception:
                pass
        except Exception as e:
            await notify.log_error(f"vc keepalive: {type(e).__name__}: {e}")


async def stop_vc():
    global _task
    state.stop["vc"] = True
    if _task and not _task.done():
        _task.cancel()
        _task = None
    if _vc is not None and _active["chat"]:
        try:
            await _vc.leave_call(_active["chat"])
        except Exception as e:
            print(f"[VC] leave: {type(e).__name__}: {e}")
    _active["chat"] = None
    if state.bot_meta:
        state.bot_meta.pop("vc_target", None)
        await _persist()


async def auto_join():
    target = _meta_target()
    if not target:
        return
    await asyncio.sleep(15)
    try:
        await start_vc(int(target))
        await notify.log(f"🎙️ Auto-join VC: {target}")
    except Exception as e:
        await notify.log_error(f"vc auto: {type(e).__name__}: {e}")


def load():
    _pkgs()
    client = state.client

    @client.on(events.NewMessage(pattern=helpers.cmd("vcstart", r"(?:\s+(.+))?"), outgoing=True))
    async def vcstart(event):
        global _task, _ready
        arg = event.pattern_match.group(1)
        await event.delete()
        status = await event.respond(helpers.wm("🎙️ Menyiapkan voice chat..."))
        try:
            chat_id, label = await _resolve_target(event, arg)
            await start_vc(chat_id, label)
            state.bot_meta = state.bot_meta or {}
            state.bot_meta["vc_target"] = int(chat_id)
            await _persist()
            await status.edit(helpers.wm(
                f"🎙️ **VC Aktif**\n"
                f"✅ Akun berdiam di `{chat_id}` ({label})\n"
                f"🔇 Mic di-mute | target disimpan utk auto-join tiap restart"
            ))
        except Exception as e:
            await status.edit(helpers.wm(f"❌ Gagal mulai VC: {e}"))

    @client.on(events.NewMessage(pattern=helpers.cmd("vcstop"), outgoing=True))
    async def vcstop(event):
        await event.delete()
        await stop_vc()
        await helpers.temp(event, helpers.wm("🎙️ Keluar dari VC & target dihapus."))

    @client.on(events.NewMessage(pattern=helpers.cmd("vcstat"), outgoing=True))
    async def vcstat(event):
        target = _meta_target()
        lib = "✅" if _ready else "❌"
        task = "🟢" if (_task and not _task.done()) else "⚪"
        chat = _active["chat"] or ("dipersiapkan" if target else "-")
        text = (
            f"**🎙️ STATUS VOICE CHAT**\n"
            f"------------------------\n"
            f"Target: `{target or '-'}`\n"
            f"VC aktif: `{chat}`\n"
            f"Keepalive: {task}\n"
            f"Library: {lib}"
        )
        await event.respond(helpers.wm(text))
        await event.delete()