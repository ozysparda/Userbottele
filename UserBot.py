"""Userbottele v2 — entry point. Jalankan: python UserBot.py [--check]"""
import asyncio
import sys
import time

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
    from modules import admin, ai, automation, media, panel, promo
    for mod in (promo, admin, automation, media, ai, panel):
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


async def _main():
    print(BANNER)
    print(f"Userbottele v{config.VERSION} — memuat modul...")

    user = _make_user_client()
    state.client = user
    state.started_at = time.time()
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

    print("[OK] Userbot berjalan. Ketik .help di Telegram untuk menu.")
    await notify.log(f"🚀 Userbot v{config.VERSION} berjalan. Owner: {me.id}")

    clients = [user.run_until_disconnected()]
    if state.bot:
        clients.append(state.bot.run_until_disconnected())
    await asyncio.gather(*clients)


def main():
    if "--check" in sys.argv:
        _run_checks()
        return
    asyncio.run(_main())


if __name__ == "__main__":
    main()