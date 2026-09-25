"""WhatsApp command bot (pyaileys) untuk GitHub Actions / lokal.

Mirip pola userbot Telegram di repo ini:
  - QR login sekali; session di folder wabot/auth
  - folder auth di-zip+gzip -> base64 -> disimpan di gist (wa_auth.b64)
  - di Actions: bootstrap = ambil snapshot dari gist, dump = simpan balik
  - workflow dispatch ulang sebelum batas ~6 jam

Env:
  WA_GIST_ID      id gist untuk snapshot auth (default meta gist)
  GIST_TOKEN      token gist (wajib utk persist session lintas boot)
  WA_ALLOWED      daftar JID / nomor yg boleh pakai command (virgul), boleh kosong = semua
  WA_QR_TIMEOUT   detik menunggu scan (0 = sampai sukses)
  GEMINI_KEY / GEMINI_MODEL  utk .ai
  WA_LOG_LEVEL    debug|info
"""
import asyncio
import base64
import gzip
import json
import logging
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
AUTH_DIR = BASE_DIR / "wabot" / "auth"
CACHE_PATH = BASE_DIR / "wabot" / "wacache.sqlite3"
GIST_ID = os.environ.get("WA_GIST_ID", "af47a5eaf5151ffa94b13c3a99dcb73a")
GIST_TOKEN = os.environ.get("GIST_TOKEN", "")

log = logging.getLogger("wabot")
PREFIX = "."

_SELF_JID = ""
_logged_once = set()


def _setup_logger():
    level = logging.DEBUG if os.environ.get("WA_LOG_LEVEL", "info") == "debug" else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.StreamHandler()])
    logging.getLogger("pyaileys").setLevel(logging.WARNING)


# ==================== AUTH SNAPSHOT (gist) ====================

def _auth_to_b64() -> str:
    """Gzip+base64 seluruh folder auth sebagai map {relpath: b64 content}."""
    import io
    files = {}
    for p in sorted(AUTH_DIR.rglob("*")):
        if p.is_file():
            rel = str(p.relative_to(AUTH_DIR)).replace("\\", "/")
            files[rel] = base64.b64encode(p.read_bytes()).decode()
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=9, mtime=0) as f:
        f.write(json.dumps(files).encode("utf-8"))
    return base64.b64encode(buf.getvalue()).decode()


def _b64_to_auth(b64: str):
    """Kebalikan _auth_to_b64(). Mengganti semua isi folder auth."""
    files = json.loads(gzip.decompress(base64.b64decode(b64)).decode("utf-8"))
    AUTH_DIR.mkdir(parents=True, exist_ok=True)
    seen = set()
    for rel, b64c in files.items():
        path = AUTH_DIR / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(b64c))
        seen.add(rel)
    for p in AUTH_DIR.rglob("*"):
        if p.is_file():
            rel = str(p.relative_to(AUTH_DIR)).replace("\\", "/")
            if rel not in seen:
                p.unlink()


def _save_auth_snapshot(text: str | None = None):
    """Simpan snapshot auth + meta ke gist (opsional jika GIST_TOKEN)."""
    if not GIST_TOKEN:
        return
    try:
        import urllib.request
        files = {"wa_auth.b64": {"content": text or _auth_to_b64()}}
        url = f"https://api.github.com/gists/{GIST_ID}"
        req = urllib.request.Request(
            url,
            data=json.dumps({"files": files}).encode("utf-8"),
            headers={"Authorization": f"token {GIST_TOKEN}",
                     "Accept": "application/vnd.github+json",
                     "User-Agent": "wabot"},
            method="PATCH",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            log.debug("snapshot auth push status=%s", resp.status)
    except Exception as e:
        log.warning("gagal push snapshot auth: %s", e)


def _fetch_auth_snapshot():
    """Ambil wa_auth.b64 dari gist; None bila tidak ada / gagal."""
    if not GIST_TOKEN:
        return None
    try:
        import urllib.request
        url = f"https://api.github.com/gists/{GIST_ID}"
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"token {GIST_TOKEN}",
                     "Accept": "application/vnd.github+json",
                     "User-Agent": "wabot"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            gist = json.loads(resp.read().decode())
        files = gist.get("files") or {}
        f = files.get("wa_auth.b64")
        return f.get("content") if f else None
    except Exception as e:
        log.warning("gagal fetch snapshot auth: %s", e)
        return None


# ==================== QR ====================

def _render_qr(url: str) -> str:
    try:
        import segno
        import io
        qr = segno.make(url, error="m")
        out = io.StringIO()
        qr.terminal(out=out, border=2)
        return out.getvalue()
    except Exception:
        return f"QR (url): {url}"


# ==================== COMMANDS ====================

def _allowed(sender, self):
    if not ALLOWED_SET:
        return True
    s = sender.lower().split(":")[0]
    me = self.lower().split(":")[0]
    return s in ALLOWED_SET or me in ALLOWED_SET


async def _on_message(client, data):
    text = (data.get("text") or "").strip()
    chat_jid = data.get("chat_jid")
    sender_jid = data.get("sender_jid") or ""
    if not text or not chat_jid:
        return
    if chat_jid.endswith("@g.us"):
        return  # hanya PM
    if not _allowed(sender_jid, _SELF_JID):
        return
    if not text.startswith(PREFIX):
        return

    parts = text[len(PREFIX):].split(maxsplit=1)
    cmd = (parts[0] if parts else "").lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd == "ping":
        await client.send_text(chat_jid, "🏓 pong")
    elif cmd == "help":
        await client.send_text(chat_jid, _help_text())
    elif cmd in ("ai", "gemini"):
        await _cmd_ai(client, chat_jid, arg)
    elif cmd:
        await client.send_text(chat_jid, f"❓ Perintah `.{cmd}` tak dikenal. Ketik `.help`.")


def _help_text():
    return (
        "*WhatsApp Userbot*\n\n"
        "`.ping` — tes koneksi\n"
        "`.help` — menu ini\n"
        "`.ai <teks>` — jawab pakai Gemini\n"
    )


async def _cmd_ai(client, chat_jid, arg):
    if not arg:
        await client.send_text(chat_jid, "ℹ️ Contoh: `.ai apa itu internet?`")
        return
    key = os.environ.get("GEMINI_KEY", "")
    model = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
    if not key:
        await client.send_text(chat_jid, "❌ GEMINI_KEY belum diatur.")
        return
    try:
        import urllib.request
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        payload = json.dumps({"contents": [{"parts": [{"text": arg}]}]}).encode()
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "wabot"},
        )
        with urllib.request.urlopen(req, timeout=40) as resp:
            body = json.loads(resp.read().decode())
        cands = body.get("candidates") or []
        if not cands:
            await client.send_text(chat_jid, "⚠️ Gemini tidak membalas.")
            return
        text = "\n".join(
            x.get("text", "") for x in (cands[0].get("content") or {}).get("parts", []) if x.get("text")
        ).strip()
        await client.send_text(chat_jid, text or "⚠️ Gemini tidak membalas.")
    except Exception as e:
        await client.send_text(chat_jid, f"⚠️ Gagal: {e}")


# ==================== MAIN ====================

async def _reboot_scheduler(stop: asyncio.Event):
    """Dispatch workflow baru sebelum batas ~6 jam, seperti bot Telegram."""
    import time
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    run_min = int(os.environ.get("WA_RUN_MINUTES", "355"))
    lead = min(int(os.environ.get("WA_REBOOT_LEAD", "300")), run_min - 5)
    target = max((run_min * 60) - lead, 60)
    token = os.environ.get("GIST_TOKEN", "")
    if not token:
        return
    start = time.monotonic()
    while not stop.is_set():
        if time.monotonic() - start >= target:
            ecp = await asyncio.to_thread(_dispatch_run, token)
            if ecp is not None:
                log.info("Dispatch reboot WA berhasil: %s", ecp)
                return  # bot baru akan menggantikan (concurrency)
            start = time.monotonic()
        await asyncio.sleep(30)


def _dispatch_run(token: str):
    import urllib.request
    url = ("https://api.github.com/repos/"
           "ozysparda/Userbottele/actions/workflows/wabot.yml/dispatches")
    data = json.dumps({"ref": "main"}).encode()
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Authorization": f"token {token}",
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "wabot"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status
    except Exception as e:
        log.warning("dispatch gagal: %s", e)
        return None


async def main():
    global _SELF_JID
    _setup_logger()
    from pyaileys import WhatsAppClient

    AUTH_DIR.mkdir(parents=True, exist_ok=True)

    # Coba pulihkan session dari gist (Actions boot baru).
    snap = _fetch_auth_snapshot()
    if snap and not (AUTH_DIR / "creds.json").exists():
        try:
            _b64_to_auth(snap)
            log.info("Session dipulihkan dari snapshot gist.")
        except Exception as e:
            log.warning("Gagal restore snapshot: %s", e)

    client, auth_state = await WhatsAppClient.from_auth_folder(
        str(AUTH_DIR), store_path=str(CACHE_PATH)
    )
    connected = asyncio.Event()

    async def on_update(update):
        if update.qr:
            print("========== SCAN QR DENGAN WHATSAPP (Settings -> Linked Devices) ==========")
            print(_render_qr(update.qr))
            print("===================== SCAN, LALU KONFIRMASI ==============================")
        if update.connection:
            log.info("connection=%s is_new_login=%s", update.connection, update.is_new_login)
            if update.connection == "open":
                connected.set()

    async def on_creds_update(_creds):
        try:
            await auth_state.save_creds()
        except Exception as e:
            log.warning("save creds: %s", e)

    client.on("connection.update", on_update)
    client.on("creds.update", on_creds_update)
    client.on("message.decrypted", lambda d: asyncio.ensure_future(_on_message(client, d)))

    await client.connect()

    timeout = int(os.environ.get("WA_QR_TIMEOUT", "0")) or None
    try:
        await asyncio.wait_for(connected.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        log.warning("QR timeout tanpa scan; keluar. Jalankan lagi untuk QR baru.")
        await client.disconnect()
        return 0

    me = getattr(getattr(client.socket, "auth", None), "creds", None)
    if me and getattr(me, "me", None) and me.me.id:
        _SELF_JID = me.me.id.split(":")[0].lower()
    log.info("WhatsApp online sebagai %s. Menunggu pesan...", _SELF_JID or "?")

    stop = asyncio.Event()
    asyncio.create_task(_reboot_scheduler(stop))

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        stop.set()
        await auth_state.save_creds()
        _save_auth_snapshot()
        await client.disconnect()
    return 0


ALLOWED_SET = set(
    x.strip().lower() for x in os.environ.get("WA_ALLOWED", "").split(",") if x.strip()
)

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))