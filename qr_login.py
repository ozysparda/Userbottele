"""Login ulang via QR — tampil di terminal, hasil session ditulis ke .env.

Pakai:  python qr_login.py
Kode ini membuat session BARU (session lama yang AuthKeyDuplicated tidak
bisa dipakai lagi). Setelah QR tampil, scan dengan Telegram HP:
    Settings -> Devices -> Scan QR / Link Desktop
Session baru otomatis menggantikan STRING_SESSION di .env lalu dicetak agar
bisa dipakai untuk update secret ENV_BASE64 di GitHub.
"""
import asyncio
import os
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _load_dotenv():
    path = BASE_DIR / ".env"
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _update_env(session_str):
    path = BASE_DIR / ".env"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    key = "STRING_SESSION"
    if re.search(rf"^{re.escape(key)}=.*$", text, flags=re.M):
        text = re.sub(rf"^{re.escape(key)}=.*$", f"{key}={session_str}", text, flags=re.M)
    else:
        text = text.rstrip() + f"\n{key}={session_str}\n"
    path.write_text(text, encoding="utf-8")
    print(f"\n[OK] STRING_SESSION baru tersimpan di {path}")


async def main():
    env = _load_dotenv()
    api_id = int(env.get("API_ID") or 0)
    api_hash = env.get("API_HASH") or ""
    if not api_id or not api_hash:
        print("ERR: API_ID/API_HASH tidak ada di .env")
        return 1

    from telethon import TelegramClient
    from telethon.network import ConnectionTcpFull
    from telethon.sessions import StringSession

    session_new = StringSession()
    client = TelegramClient(session_new, api_id, api_hash,
                            connection_retries=5, flood_sleep_threshold=10)
    await client.connect()

    qr = await client.qr_login()
    try:
        import segno
        qr_img = segno.make(qr.url, error="m")
    except Exception:
        qr_img = None

    if qr_img is not None:
        # Render QR besar & terang untuk di-scan dari layar terminal
        try:
            qr_img.terminal(border=2, invert=False)
        except Exception:
            qr_img.terminal_inline(border=2)
    else:
        print("QR preview tidak tersedia, URL sementara di bawah (copy ke pembuat QR):")
        print(qr.url[:150])

    print()
    print("Scan QR di atas dengan aplikasi Telegram (Settings -> Devices -> Scan QR).")
    print("Menunggu scan... (timeout 120 detik)")

    try:
        user = await asyncio.wait_for(qr.wait(), timeout=120)
    except asyncio.TimeoutError:
        print("Timeout: QR kedaluwarsa. Jalankan ulang skrip.")
        return 1

    name = getattr(user, "first_name", "") or str(getattr(user, "id", "?"))
    print(f"Berhasil login sebagai: {name} (@{getattr(user, 'username', '')})")
    print("Mengambil session baru...")
    saved = session_new.save()
    await client.disconnect()
    _update_env(saved)
    print("Selesai. Copy nilai session ini untuk secret ENV_BASE64:")
    print("-" * 40)
    print(saved)
    print("-" * 40)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))