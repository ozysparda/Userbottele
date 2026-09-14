"""Userbottele v2 — entry point. Jalankan: python UserBot.py [--check]"""
import asyncio
import json
import sys
import time
from pathlib import Path

import urllib.request

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telethon.sessions import StringSession

from core import config, inline, notify
from core.state import state

BANNER = r"""
   _   _                   ____          _ _ _            
  | | | |___  ___ _ __ ___| __ )  ___   | | | |___   ___ 
  | | | / __|/ _ \ '__/ _ \  _ \ / _ \  | | | / __| / _ \
  | |_| \__ \  __/ | |  __/ |_) |  __/  | |_| \__ \|  __/
   \___/|___/\___|_|  \___|____/ \___|   \___/|___/ \___|
"""


META_PATH = Path(__file__).resolve().parent / "data" / "bot_meta.json"


def _fetch_gist_meta():
    gid = config.get("GIST_ID")
    tok = config.get("GIST_TOKEN")
    if not (gid and tok):
        return None
    try:
        req = urllib.request.Request(
            f"https://api.github.com/gists/{gid}",
            headers={"Authorization": f"Bearer {tok}",
                     "Accept": "application/vnd.github+json",
                     "User-Agent": "userbottele"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        content = (data.get("files") or {}).get("bot_meta.json", {}).get("content") or ""
        try:
            return json.loads(content)
        except Exception:
            return {}
    except Exception:
        return None


def _save_gist_meta(meta):
    gid = config.get("GIST_ID")
    tok = config.get("GIST_TOKEN")
    if not (gid and tok):
        return False
    try:
        body = json.dumps({"files": {"bot_meta.json":
                                     {"content": json.dumps(meta)}}}).encode()
        req = urllib.request.Request(
            f"https://api.github.com/gists/{gid}",
            data=body, method="PATCH",
            headers={"Authorization": f"Bearer {tok}",
                     "Content-Type": "application/json",
                     "Accept": "application/vnd.github+json",
                     "User-Agent": "userbottele"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status == 200
    except Exception:
        return False


def _load_bot_meta():
    meta = {}
    if META_PATH.exists():
        try:
            meta = json.loads(META_PATH.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    if not meta.get("first_start"):
        meta["first_start"] = int(time.time())
    meta.setdefault("restarts", 0)
    return meta


def _save_bot_meta(meta):
    META_PATH.parent.mkdir(parents=True, exist_ok=True)
    META_PATH.write_text(json.dumps(meta), encoding="utf-8")


async def _persist_meta():
    _save_bot_meta(state.bot_meta)
    await asyncio.to_thread(_save_gist_meta, state.bot_meta)


def _make_user_client():
    session = StringSession(config.STRING_SESSION) if config.STRING_SESSION else "userbot"
    return TelegramClient(session, config.API_ID, config.API_HASH, flood_sleep_threshold=10)


def _make_bot_client():
    return TelegramClient("bot_session", config.API_ID, config.API_HASH)


async def _interactive_login(client):
    if not client.is_connected():
        await client.connect()
    if await client.is_user_authorized():
        return True
    print("[!] Login diperlukan.")
    phone = input("Masukkan nomor HP (+62xxxxxxxxxx): ").strip()
    try:
        await client.send_code_request(phone)
    except Exception as e:
        print(f"[X] Gagal kirim kode: {e}")
        return False
    code = input("Masukkan kode OTP: ").strip()
    try:
        await client.sign_in(phone, code=code)
    except (SessionPasswordNeededError,):
        password = input("Akun memakai 2FA, masukkan password: ").strip()
        try:
            await client.sign_in(password=password)
        except Exception as e:
            print(f"[X] 2FA gagal: {e}")
            return False
    except Exception as e:
        print(f"[X] Login gagal: {e}")
        return False
    return True


async def _start_bot(bot):
    if not config.BOT_TOKEN:
        return None
    try:
        await bot.start(bot_token=config.BOT_TOKEN)
        state.bot = bot
        me = await bot.get_me()
        print(f"[OK] Bot UI aktif: @{me.username}")
        return bot
    except Exception as e:
        print(f"[!] Bot UI mati (lanjut tanpa tombol): {e}")
        return None


def _register_modules():
    from modules import admin, ai, automation, gc, media, mute, panel, promo, tools, vc
    for mod in (promo, admin, automation, gc, media, ai, mute, panel, tools, vc):
        mod.load()


def _run_checks():
    errors = []
    if not config.API_ID:
        errors.append("API_ID belum diatur di .env")
    if not config.API_HASH:
        errors.append("API_HASH belum diatur di .env")
    if errors:
        print("[X] ".join([""] + errors))
        print("    Copy .env.example -> .env lalu isi API_ID & API_HASH dari https://my.telegram.org")
        sys.exit(1)
    state.client = TelegramClient(None, config.API_ID, config.API_HASH)
    _register_modules()
    print(f"[OK] Semua {len(inline.HELP)} kategori & modul dimuat. Config valid. Versi {config.VERSION}")


async def _generate_string_session():
    print(BANNER)
    print("Mode: buat STRING_SESSION untuk deploy (Telegram akan minta kode OTP).")
    client = TelegramClient(
        StringSession(), config.API_ID, config.API_HASH, flood_sleep_threshold=10
    )
    if not (await _interactive_login(client)):
        sys.exit(1)
    me = await client.get_me()
    print(f"[OK] Login sebagai: {me.first_name} (ID: {me.id})")
    print("\n[OK] STRING_SESSION kamu (RAHASIA, jangan dibagikan):\n")
    print(client.session.save())
    print("\n[!] Masukkan ke env var STRING_SESSION di platform deploy, lalu jalankan UserBot.py.")
    await client.disconnect()


async def _main():
    print(BANNER)
    print(f"Userbottele v{config.VERSION} — memuat modul...")

    user = _make_user_client()
    state.client = user
    meta = await asyncio.to_thread(_fetch_gist_meta)
    if meta is None:
        meta = _load_bot_meta()
    else:
        _save_bot_meta(meta)
    meta["restarts"] += 1
    _save_bot_meta(meta)
    await asyncio.to_thread(_save_gist_meta, meta)
    state.bot_meta = meta
    state.started_at = float(meta["first_start"])
    state.save_meta = _persist_meta
    state.flood.start()

    if not (await _interactive_login(user)):
        sys.exit(1)

    me = await user.get_me()
    state.owner_id = config.OWNER_ID or me.id
    print(f"[OK] Login sebagai: {me.first_name} (ID: {me.id})")

    await _start_bot(_make_bot_client())

    _register_modules()
    inline.attach()
    state.ui = True

    from modules import vc as vc_mod
    if meta.get("vc_target"):
        asyncio.create_task(vc_mod.auto_join())

    print("[OK] Userbot berjalan. Ketik .help di Telegram untuk menu.")
    await notify.log(f"🚀 Userbot v{config.VERSION} berjalan. Owner: {me.id}")

    clients = [user.run_until_disconnected()]
    if state.bot:
        clients.append(state.bot.run_until_disconnected())
    await asyncio.gather(*clients)


def main():
    if "--string-session" in sys.argv:
        asyncio.run(_generate_string_session())
        return
    if "--check" in sys.argv:
        _run_checks()
        return
    asyncio.run(_main())


if __name__ == "__main__":
    main()