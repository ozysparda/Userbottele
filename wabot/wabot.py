"""WhatsApp command bot (pyaileys) untuk GitHub Actions / lokal.

Mirip pola userbot Telegram di repo ini:
  - QR login sekali; session di folder wabot/auth
  - folder auth di-zip+gzip -> base64 -> disimpan di gist (wa_auth.b64)
  - di Actions: bootstrap = ambil snapshot dari gist, dump = simpan balik
  - workflow dispatch ulang sebelum batas ~6 jam

Fitur:
  - Role system: OWNER (WA_OWNER) + anggota (config.json di dalam auth)
  - .add/.rem (owner) + notifikasi otomatis ke yg diberi akses
  - .allowgroup/.denygroup (owner) -> akses grup
  - Bio/business description: online/offline/restart via raw IQ xmlns=w:biz
  - .owner, .ai (Gemini), .sticker, .toimg, .dl (yt-dlp), .tagall, .bc, .sched
  - .cuaca, .tr (translate), .qr, .short, .calc, .random
  - .yt (cari video), .tts (suara), .music (audio), .remind
  - .autoread, .ar keyword (kata kunci), anti-leave/anti-join grup (owner)

Env:
  WA_GIST_ID      id gist untuk snapshot auth (default meta gist)
  GIST_TOKEN      token gist (wajib utk persist session lintas boot)
  WA_OWNER        jid/nomor owner (default 6282235337915@s.whatsapp.net)
  WA_ALLOWED      daftar jid/nomor tambahan yg boleh pakai command (virgul)
  WA_QR_TIMEOUT   detik menunggu scan (0 = sampai sukses)
  GEMINI_KEY / GEMINI_MODEL  utk .ai
  WA_LOG_LEVEL    debug|info
"""
import asyncio
import ast
import base64
import gzip
import json
import logging
import os
import random
import sys
import time
import urllib.parse
import urllib.request
from io import BytesIO
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

_DEFAULT_OWNER = "6282235337915@s.whatsapp.net"

CONFIG_FILENAME = "wabot_config.json"


def _setup_logger():
    level = logging.DEBUG if os.environ.get("WA_LOG_LEVEL", "info") == "debug" else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.StreamHandler()])
    logging.getLogger("pyaileys").setLevel(logging.WARNING)


# ==================== CONFIG (role system) ====================

def _config_path() -> Path:
    return AUTH_DIR / CONFIG_FILENAME


def _load_config() -> dict:
    try:
        with open(_config_path(), encoding="utf-8") as f:
            cfg = json.load(f)
        if isinstance(cfg, dict):
            return cfg
    except Exception:
        pass
    return {"owner": "", "users": [], "groups": [], "schedules": [], "autoreply": {}}


def _save_config(cfg: dict):
    try:
        AUTH_DIR.mkdir(parents=True, exist_ok=True)
        with open(_config_path(), "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.warning("gagal simpan config: %s", e)


def _norm_number(n: str) -> str:
    """Normalisasi nomor HP -> jid whatsapp. Terima 08xx, 628xx, +62, atau jid."""
    n = (n or "").strip().lower()
    dirty = ("+", "-", " ", "(", ")", ".", ",", "\t")
    for ch in dirty:
        n = n.replace(ch, "")
    if "@" in n:
        return n.split(":")[0].split("@")[0] + "@s.whatsapp.net"
    if n.startswith("0"):
        n = "62" + n[1:]
    elif not n.startswith("62"):
        n = "62" + n
    return n + "@s.whatsapp.net"


def _jid_key(jid: str) -> str:
    """Kunci normal utk perbandingan jid: nomor tanpa device/domain."""
    return (jid or "").lower().split(":")[0].split("@")[0].strip()


def _owner() -> str:
    env = os.environ.get("WA_OWNER", "").strip()
    if env:
        return _norm_number(env)
    cfg_owner = (_load_config().get("owner") or "").strip()
    if cfg_owner:
        return _cfg_jid(cfg_owner)
    return _DEFAULT_OWNER


def _cfg_jid(j: str) -> str:
    return _norm_number(j) if "@" not in j or not j.endswith("@s.whatsapp.net") else j


def _is_owner(sender: str) -> bool:
    return _jid_key(sender) == _jid_key(_owner())


def _is_user(sender: str) -> bool:
    cfg = _load_config()
    users = set(_jid_key(x) for x in cfg.get("users", []))
    return _jid_key(sender) in users


def _allowed(sender: str) -> bool:
    """Untuk chat PM: owner + anggota yg di-add owner."""
    if _is_owner(sender):
        return True
    if _is_user(sender):
        return True
    legacy = set(
        _jid_key(_norm_number(x)) for x in os.environ.get("WA_ALLOWED", "").split(",") if x.strip()
    )
    return _jid_key(sender) in legacy


def _group_ok(chat_jid: str) -> bool:
    cfg = _load_config()
    groups = set(_jid_key(x) for x in cfg.get("groups", []))
    return _jid_key(chat_jid) in groups


# Cache menit LID -> PN hasil resolve (nama: _lid_pn_cache).
_LID_PN_CACHE: dict[str, str] = {}


async def _resolve_pn(client, jid: str) -> str:
    """Resolve LID (@lid) -> nomor PN (@s.whatsapp.net).

    Sumber: (1) mapping internal pyaileys dari creds/group, (2) cache lokal,
    (3) USync query terhadap owner+users utk menemukan pasangan lid->pn.
    Jika tak ditemukan, kembalikan jid asli (akrab {jadwal}).
    """
    jid = (jid or "").strip()
    if not jid:
        return jid
    if jid.lower().endswith("@s.whatsapp.net"):
        return jid
    if not jid.lower().endswith("@lid"):
        return jid

    key = _jid_key(jid)

    # 1) mapping internal pyaileys (creds me.id<->me.lid).
    try:
        alt = client._alt_jid_preserve_device(jid)
        if alt and alt.lower().endswith("@s.whatsapp.net"):
            _LID_PN_CACHE[key] = alt
            return alt.lower()
    except Exception:
        pass

    # 2) cache dari config (disimpan saat sukses resolve sebelumnya).
    cfg = _load_config()
    lidmap = cfg.get("lidmap") or {}
    if key in lidmap and lidmap[key].lower().endswith("@s.whatsapp.net"):
        _LID_PN_CACHE[key] = lidmap[key]
        return lidmap[key].lower()

    # 3) USync query: minta mapping untuk owner + semua user; cari lid cocok.
    try:
        known = [_owner()]
        for u in cfg.get("users", []):
            known.append(_cfg_jid(u))
        known = list(dict.fromkeys(known))
        if known:
            res = await client.socket.execute_usync_query(
                known, context="message", mode="query", timeout_s=12
            )
            found: str | None = None
            for r in res:
                rid = _jid_key(r.id)
                rlid = (r.lid or "").strip()
                if not r.id or not rlid:
                    continue
                lidmap[rid] = rlid.lower()
                lidmap[_jid_key(rlid)] = str(r.id).lower()
                if _jid_key(rlid) == key:
                    found = f"{rid}@s.whatsapp.net"
            if found:
                lidmap[key] = found
                cfg["lidmap"] = lidmap
                _save_config(cfg)
                _LID_PN_CACHE[key] = found
                log.info("LID %s -> PN %s (via usync owner/users)", jid, found)
                return found.lower()
    except Exception as e:
        log.warning("resolve LID %s via usync gagal: %s", jid, e)

    log.warning("LID %s belum bisa di-resolve ke PN; diperlakukan apa adanya", jid)
    return jid


def _is_group(chat_jid: str) -> bool:
    return (chat_jid or "").endswith("@g.us")


# ==================== AUTH SNAPSHOT (gist) ====================

def _auth_to_b64() -> str:
    """Gzip+base64 seluruh folder auth (termasuk config) sebagai map {relpath: b64 content}."""
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
    """Kebalikan _auth_to_b64(). Mengganti semua isi folder auth (termasuk config)."""
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
    """Simpan snapshot auth + config ke gist (opsional jika GIST_TOKEN)."""
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


def _save_qr_svg(url: str):
    """Simpan QR sebagai SVG + coba buka di browser (scan dari layar lebih mudah)."""
    try:
        import segno
        svg_path = BASE_DIR / "wabot" / "wa_qr.svg"
        segno.make(url, error="m").save(str(svg_path), scale=10, border=2,
                                        dark="black", light="white")
        print(f"[INFO] QR SVG tersimpan: {svg_path}")
        if sys.platform == "win32":
            import subprocess
            subprocess.Popen(["cmd", "/c", "start", "", str(svg_path)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"[INFO] QR SVG gagal disimpan: {e}")


# ==================== BIO (business description) ====================

async def _set_bio(client, text: str):
    """Update deskripsi bisnis (bio di WA Business) via raw IQ xmlns=w:biz.

    Mengikuti updateBusinessProfile Baileys. Best-effort: gagal hanya dicatat.
    """
    if not text:
        return
    try:
        from pyaileys.socket import BinaryNode
        node = BinaryNode(
            tag="iq",
            attrs={"to": "s.whatsapp.net", "type": "set", "xmlns": "w:biz"},
            content=[
                BinaryNode(
                    tag="business_profile",
                    attrs={},
                    content=[
                        BinaryNode(tag="description", attrs={}, content=text),
                    ],
                )
            ],
        )
        # Fire-and-forget: beberapa impl kirim tanpa menunggu respons XML.
        await client.socket.send_node(node)
        log.info("bio/business description di-set: %s", text[:60])
    except Exception as e:
        log.warning("gagal set bio (%s): %s", text[:40], e)


# ==================== COMMANDS ====================

def _extract_media(inner):
    """Ambil media dari pesan proto (permalink/quote).

    Returns (media_type | None, media_msg) dengan media_msg siap utk
    client.download_message_media(). Types: image|video|sticker|audio|document.
    """
    if inner is None:
        return None, None
    has = getattr(inner, "HasField", None)
    if not callable(has):
        return None, None
    for t, field in (("image", "imageMessage"), ("video", "videoMessage"),
                     ("sticker", "stickerMessage"), ("audio", "audioMessage"),
                     ("document", "documentMessage")):
        if has(field):
            return t, inner
    # Reply/quote: extendedTextMessage.contextInfo.quotedMessage
    try:
        etm = inner.extendedTextMessage if has("extendedTextMessage") else None
        if etm is not None and etm.HasField("contextInfo"):
            ci = etm.contextInfo
            if ci.HasField("quotedMessage"):
                q = ci.quotedMessage
                for t, field in (("image", "imageMessage"), ("video", "videoMessage"),
                                 ("sticker", "stickerMessage"), ("audio", "audioMessage"),
                                 ("document", "documentMessage")):
                    if getattr(q, "HasField", None) and q.HasField(field):
                        return t, q
    except Exception:
        pass
    return None, None


def _make_sticker_bytes(data: bytes, *, animated: bool = False) -> bytes | None:
    """Konversi gambar/stiker -> webp 512x512 utk send_sticker."""
    try:
        from PIL import Image, ImageOps
    except Exception as e:
        log.warning("PIL tidak tersedia utk sticker: %s", e)
        return None
    try:
        im = Image.open(BytesIO(data))
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGBA")
        im.thumbnail((512, 512))
        canvas = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
        canvas.paste(im, ((512 - im.width) // 2, (512 - im.height) // 2), im)
        out = BytesIO()
        canvas.save(out, format="WEBP", quality=88, method=6)
        return out.getvalue()
    except Exception as e:
        log.warning("gagal buat sticker: %s", e)
        return None


async def _send_read_receipt(client, chat_jid: str, sender_jid: str, msg_id: str):
    """Tandai pesan sudah dibaca (receipt type=read) utk autoread."""
    if not msg_id or not chat_jid:
        return
    try:
        from pyaileys.socket import BinaryNode
        attrs: dict[str, str] = {"id": msg_id, "to": chat_jid, "type": "read"}
        content = None
        if _is_group(chat_jid) and sender_jid:
            attrs["participant"] = sender_jid
            content = [BinaryNode(tag="read_ids", content=[])]
        await client.socket.send_node(BinaryNode(tag="receipt", attrs=attrs, content=content))
    except Exception as e:
        log.debug("autoread gagal: %s", e)


async def _group_participants_update(client, group_jid: str, action: str, target_jid: str):
    """Set/unset member grup (add/remove/promote/demote) via raw IQ w:g2."""
    if not _is_group(group_jid) or not target_jid:
        return False
    try:
        from pyaileys.socket import BinaryNode
        import secrets
        node = BinaryNode(
            tag="iq",
            attrs={
                "to": group_jid,
                "type": "set",
                "xmlns": "w:g2",
                "id": secrets.token_hex(8),
            },
            content=[BinaryNode(tag="participant", attrs={"action": action, "jid": target_jid})],
        )
        resp = await client.socket.query(node, timeout_s=15)
        etype = (resp.attrs or {}).get("type")
        return etype == "result"
    except Exception as e:
        log.warning("group %s %s %s gagal: %s", action, target_jid, group_jid, e)
        return False


async def _on_message(client, data):
    text = (data.get("text") or "").strip()
    chat_jid = data.get("chat_jid")
    sender_jid = data.get("sender_jid") or ""
    inner = data.get("message")
    msg_id = data.get("id") or ""
    if not chat_jid:
        return
    log.info("pesan masuk: from=%s chat=%s teks=%r", sender_jid, chat_jid, text[:60])

    # Autoread: tandai dibaca.
    cfg = _load_config()
    if cfg.get("autoread"):
        asyncio.ensure_future(_send_read_receipt(client, chat_jid, sender_jid, msg_id))

    # Resolve LID -> PN utk pengecekan akses.
    resolved_sender = await _resolve_pn(client, sender_jid)

    # Mode grup: hanya grup yg di-allow owner.
    if _is_group(chat_jid):
        if not _group_ok(chat_jid):
            log.info("grup %s belum di-allow; diabaikan", chat_jid)
            return
    else:
        if not _allowed(resolved_sender):
            log.info("pengirim %s tanpa akses; diabaikan", resolved_sender)
            return

    # Auto-reply keyword (utk pesan biasa, bukan perintah).
    if not text.startswith(PREFIX):
        ar = _load_config().get("autoreply")
        if isinstance(ar, str):
            ar = {"on": bool(ar.strip()), "text": ar.strip(), "keywords": {}}
        replied = False
        if ar and ar.get("on"):
            low = text.lower()
            for kw, balas in (ar.get("keywords") or {}).items():
                if kw and kw.lower() in low:
                    await client.send_text(chat_jid, balas)
                    replied = True
                    break
            if not replied and (ar.get("text") or "").strip():
                await client.send_text(chat_jid, ar["text"].strip())
        return

    parts = text[len(PREFIX):].split(maxsplit=1)
    cmd = (parts[0] if parts else "").lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd == "ping":
        await client.send_text(chat_jid, "🏓 pong")
    elif cmd in ("help", "menu"):
        await client.send_text(chat_jid, _help_text(_is_owner(resolved_sender)))
    elif cmd == "owner":
        await client.send_text(chat_jid, _owner_text())
    elif cmd in ("ai", "gemini"):
        await _cmd_ai(client, chat_jid, arg)
    elif cmd in ("add", "grant"):
        await _cmd_add(client, chat_jid, resolved_sender, arg)
    elif cmd in ("rem", "revoke"):
        await _cmd_rem(client, chat_jid, resolved_sender, arg)
    elif cmd in ("users", "list"):
        await _cmd_users(client, chat_jid, resolved_sender)
    elif cmd in ("allowgroup", "allowg"):
        await _cmd_allowgroup(client, chat_jid, resolved_sender, arg)
    elif cmd in ("denygroup", "denyg"):
        await _cmd_denygroup(client, chat_jid, resolved_sender, arg)
    elif cmd == "groups":
        await _cmd_groups(client, chat_jid, resolved_sender)
    elif cmd == "id":
        await client.send_text(
            chat_jid,
            f"chat: `{chat_jid}`\nsender: `{sender_jid}`\nresolved: `{resolved_sender}`",
        )
    elif cmd in ("sticker", "stk"):
        await _cmd_sticker(client, chat_jid, inner)
    elif cmd == "toimg":
        await _cmd_toimg(client, chat_jid, inner)
    elif cmd in ("dl", "download"):
        await _cmd_dl(client, chat_jid, arg)
    elif cmd in ("tagall", "all"):
        await _cmd_tagall(client, chat_jid, arg)
    elif cmd == "bc":
        await _cmd_bc(client, chat_jid, resolved_sender, arg)
    elif cmd in ("sched", "schedule"):
        await _cmd_sched(client, chat_jid, resolved_sender, arg)
    elif cmd == "schedlist":
        await _cmd_schedlist(client, chat_jid)
    elif cmd in ("scheddel", "schedcancel"):
        await _cmd_scheddel(client, chat_jid, resolved_sender, arg)
    elif cmd in ("ar", "autoreply"):
        await _cmd_ar(client, chat_jid, resolved_sender, arg)
    elif cmd == "autoread":
        await _cmd_autoread(client, chat_jid, resolved_sender, arg)
    elif cmd in ("cuaca", "weather"):
        await _cmd_cuaca(client, chat_jid, arg)
    elif cmd in ("tr", "translate"):
        await _cmd_tr(client, chat_jid, arg)
    elif cmd == "qr":
        await _cmd_qr(client, chat_jid, arg)
    elif cmd in ("short", "shorten"):
        await _cmd_short(client, chat_jid, arg)
    elif cmd == "calc":
        await _cmd_calc(client, chat_jid, arg)
    elif cmd == "random":
        await _cmd_random(client, chat_jid, arg)
    elif cmd in ("yt", "youtube"):
        await _cmd_yt(client, chat_jid, arg)
    elif cmd == "tts":
        await _cmd_tts(client, chat_jid, arg)
    elif cmd in ("music", "lagu"):
        await _cmd_music(client, chat_jid, arg)
    elif cmd in ("remind", "reminder"):
        await _cmd_remind(client, chat_jid, resolved_sender, arg)
    elif cmd in ("kick", "remove"):
        await _cmd_kick(client, chat_jid, resolved_sender, arg)
    elif cmd == "addmember":
        await _cmd_addmember(client, chat_jid, resolved_sender, arg)
    elif cmd == "antileave":
        await _cmd_antileave(client, chat_jid, resolved_sender)
    elif cmd == "antijoin":
        await _cmd_antijoin(client, chat_jid, resolved_sender)
    elif cmd in ("sholat", "jadwalsholat"):
        await _cmd_sholat(client, chat_jid, arg)
    elif cmd == "hijri":
        await _cmd_hijri(client, chat_jid)
    elif cmd == "qibla":
        await _cmd_qibla(client, chat_jid, arg)
    elif cmd == "hadits":
        await _cmd_hadits(client, chat_jid, arg)
    elif cmd in ("gempa", "gempaterkini"):
        await _cmd_gempa(client, chat_jid)
    elif cmd == "wiki":
        await _cmd_wiki(client, chat_jid, arg)
    elif cmd == "lirik":
        await _cmd_lirik(client, chat_jid, arg)
    elif cmd in ("lokasi", "maps", "map"):
        await _cmd_lokasi(client, chat_jid, arg)
    elif cmd in ("kontak", "contact"):
        await _cmd_kontak(client, chat_jid, arg)
    elif cmd == "poll":
        await _cmd_poll(client, chat_jid, arg)
    elif cmd in ("stext", "textsticker"):
        await _cmd_stext(client, chat_jid, arg)
    elif cmd in ("quotes", "motivasi", "quote"):
        await _cmd_quotes(client, chat_jid)
    elif cmd == "cerpen":
        await _cmd_cerpen(client, chat_jid)
    elif cmd == "pantun":
        await _cmd_pantun(client, chat_jid)
    elif cmd in ("usd", "kurs"):
        await _cmd_kurs(client, chat_jid, arg)
    elif cmd in ("info", "infogrup"):
        await _cmd_infogrup(client, chat_jid)
    elif cmd == "listgrup":
        await _cmd_listgrup(client, chat_jid)
    elif cmd:
        await client.send_text(chat_jid, f"❓ Perintah `.{cmd}` tak dikenal. Ketik `.help`.")


def _owner_text() -> str:
    return (
        "👑 *OWNER*\n\n"
        "*Akhmad Faroyzi Hendra Saputra*\n"
        "Developer & pembuat sistem userbot ini.\n\n"
        "• Lead Team Develop — Archid Sydney IT Corp, Australia\n"
        "• Lead Team IT Develop — Dayang Org, NTB\n"
        "• Wakil provinsi di Lomba LKS SMK 2018\n"
        "• Publisher jurnal & artikel terindeks Google Scholar & ResearchGate\n"
        "• Fasih: Indonesia, English (British), Jawa, Sasak, Español"
    )


def _help_text(is_owner: bool) -> str:
    lines = [
        "*WhatsApp Userbot*",
        "",
        "`.ping` — tes koneksi",
        "`.help` — menu ini",
        "`.owner` — info owner",
        "`.ai <teks>` — jawab pakai Gemini",
        "`.sticker` / `.stk` — balas foto/stiker jadi stiker",
        "`.toimg` — balas stiker jadi gambar",
        "`.dl <url>` — download video/audio/foto (IG|FB|YT|TikTok|Pinterest)",
        "`.tagall <teks>` — sebut semua member grup",
        "`.cuaca <kota>` — info cuaca",
        "`.tr <kode> <teks>` — translate (cth: `.tr en halo`)",
        "`.qr <teks>` — buat kode QR",
        "`.short <url>` — pendekkan URL",
        "`.calc <ekspresi>` — kalkulator",
        "`.random <min> <maks>` — angka acak",
        "`.yt <judul>` — cari video YouTube",
        "`.tts <teks>` — text-to-speech",
        "`.music <judul>` — cari & kirim audio",
        "`.sholat <kota>` — jadwal sholat",
        "`.hijri` — tanggal hijriah",
        "`.qibla <kota>` — arah kiblat",
        "`.hadits [kitab]` — hadits random",
        "`.gempa` — gempa terkini (BMKG)",
        "`.wiki <topik>` — ringkasan dari Wikipedia",
        "`.lirik <judul>` — lirik lagu",
        "`.lokasi <lat>,<lon> <label>` — kirim lokasi",
        "`.kontak <nomor> <nama>` — kirim kartu kontak",
        "`.poll soal | pilihan1 | pilihan2` — buat poll",
        "`.stext <teks>` — buat stiker teks",
        "`.quotes` — motivasi acak",
        "`.cerpen` — cerpen acak",
        "`.pantun` — pantun acak",
        "`.id` — info id chat/sender",
    ]
    if is_owner:
        lines += [
            "",
            "*Admin (owner):*",
            "`.add <nomor>` — beri akses + auto-notif",
            "`.rem <nomor>` — cabut akses",
            "`.users` — daftar yg boleh akses",
            "`.allowgroup` — izinkan grup ini",
            "`.denygroup` — cabut izin grup ini",
            "`.groups` — daftar grup diizinkan",
            "`.bc <teks>` — broadcast ke semua yg punya akses",
            "`.sched <HH:MM> <teks>` — jadwal pesan (setiap hari)",
            "`.schedlist` / `.scheddel <id>`",
            "`.remind <HH:MM> <teks>` — pengingat ke PM",
            "`.ar <teks>` — auto-reply default (kosong utk off)",
            "`.ar kw <kata>; <balasan>` — auto-reply berdasar kata kunci",
            "`.ar list` / `.ar del <kata>`",
            "`.autoread on|off` — tandai pesan dibaca otomatis",
            "`.kick <nomor>` / `.addmember <nomor>` (dalam grup)",
            "`.antileave` — kick member yg keluar-masuk grup ini",
            "`.antijoin` — kick member baru yg bukan akses (grup ini)",
            "`.info` — info grup (tempat bot berada)",
        ]
    return "\n".join(lines)


async def _ai_opencode(arg: str):
    """Jawab via opencode CLI (teks murni). Kembali None bila tak tersedia/gagal."""
    import shutil
    import tempfile
    exe = shutil.which("opencode")
    if not exe:
        return None
    try:
        tmp = Path(tempfile.gettempdir()) / "wabot-ai"
        tmp.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, NO_COLOR="1")
        proc = await asyncio.create_subprocess_exec(
            exe, "run",
            "Jawab pertanyaan ini dalam teks biasa Indonesia, singkat & padat, "
            "tanpa menggunakan tools dan tanpa mengubah/membaca file apa pun:\n\n" + arg[:1500],
            cwd=str(tmp),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=env,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=90)
        txt = out.decode("utf-8", "replace").strip()
        return txt or None
    except Exception as e:
        log.debug("opencode gagal: %s", e)
        return None


async def _cmd_ai(client, chat_jid, arg):
    if not arg:
        await client.send_text(chat_jid, "ℹ️ Contoh: `.ai apa itu internet?`")
        return
    # Prefer opencode CLI (teks); fallback Gemini bila tak tersedia.
    if os.environ.get("WA_AI_BACKEND", "opencode").lower() != "gemini":
        jawab = await _ai_opencode(arg)
        if jawab:
            await client.send_text(chat_jid, jawab[:4000])
            return
    key = os.environ.get("GEMINI_KEY", "")
    model = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
    if not key:
        await client.send_text(chat_jid, "❌ GEMINI_KEY belum diatur & opencode tak tersedia.")
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


async def _cmd_add(client, chat_jid, sender_jid, arg):
    if not _is_owner(sender_jid):
        await client.send_text(chat_jid, "⛔ Khusus owner.")
        return
    jid = _norm_number(arg)
    if not jid:
        await client.send_text(chat_jid, "ℹ️ Contoh: `.add 628123456789`")
        return
    cfg = _load_config()
    users = list(cfg.get("users", []))
    key = _jid_key(jid)
    if key not in set(_jid_key(x) for x in users):
        users.append(jid)
        cfg["users"] = users
        _save_config(cfg)
        _save_auth_snapshot()
        await client.send_text(chat_jid, f"✅ `{jid}` ditambahkan.")
        try:
            await client.send_text(
                jid,
                "🎉 *Akses diberikan!*\n"
                "Owner telah memberimu akses userbot ini.\n"
                "Ketik `.help` untuk daftar perintah.",
            )
            await client.send_text(chat_jid, "📨 Notifikasi akses terkirim.")
        except Exception as e:
            await client.send_text(chat_jid, f"⚠️ Notif gagal: {e}")
    else:
        await client.send_text(chat_jid, f"ℹ️ `{jid}` sudah punya akses.")


async def _cmd_rem(client, chat_jid, sender_jid, arg):
    if not _is_owner(sender_jid):
        await client.send_text(chat_jid, "⛔ Khusus owner.")
        return
    jid = _norm_number(arg)
    if not jid:
        await client.send_text(chat_jid, "ℹ️ Contoh: `.rem 628123456789`")
        return
    cfg = _load_config()
    key = _jid_key(jid)
    users = [x for x in cfg.get("users", []) if _jid_key(x) != key]
    cfg["users"] = users
    _save_config(cfg)
    _save_auth_snapshot()
    await client.send_text(chat_jid, f"🗑 `{jid}` akses dicabut.")


async def _cmd_users(client, chat_jid, sender_jid):
    if not _is_owner(sender_jid):
        await client.send_text(chat_jid, "⛔ Khusus owner.")
        return
    cfg = _load_config()
    users = cfg.get("users", []) or []
    body = "*Usernames dengan akses:*\n" if users else "*Belum ada anggota.*\n"
    owner_jid = _owner()
    body += f"👑 Owner: `{owner_jid}`\n"
    for u in users:
        body += f"• `{u}`\n"
    await client.send_text(chat_jid, body.strip())


async def _cmd_allowgroup(client, chat_jid, sender_jid, arg):
    if not _is_owner(sender_jid):
        await client.send_text(chat_jid, "⛔ Khusus owner.")
        return
    target = arg.strip().lower() or chat_jid
    cfg = _load_config()
    groups = list(cfg.get("groups", []))
    key = _jid_key(target)
    if key not in set(_jid_key(x) for x in groups):
        groups.append(target)
        cfg["groups"] = groups
        _save_config(cfg)
        _save_auth_snapshot()
        await client.send_text(chat_jid, f"✅ Grup `{target}` diizinkan.")
    else:
        await client.send_text(chat_jid, f"ℹ️ Grup `{target}` sudah diizinkan.")


async def _cmd_denygroup(client, chat_jid, sender_jid, arg):
    if not _is_owner(sender_jid):
        await client.send_text(chat_jid, "⛔ Khusus owner.")
        return
    target = arg.strip().lower() or chat_jid
    cfg = _load_config()
    key = _jid_key(target)
    groups = [x for x in cfg.get("groups", []) if _jid_key(x) != key]
    cfg["groups"] = groups
    _save_config(cfg)
    _save_auth_snapshot()
    await client.send_text(chat_jid, f"🗑 Grup `{target}` dicabut.")


async def _cmd_groups(client, chat_jid, sender_jid):
    if not _is_owner(sender_jid):
        await client.send_text(chat_jid, "⛔ Khusus owner.")
        return
    cfg = _load_config()
    groups = cfg.get("groups", []) or []
    body = "*Grup diizinkan:*\n" if groups else "*Belum ada grup diizinkan.*"
    for g in groups:
        body += f"• `{g}`\n"
    await client.send_text(chat_jid, body.strip())


async def _cmd_sticker(client, chat_jid, inner):
    mtype, media = _extract_media(inner)
    if not media:
        await client.send_text(chat_jid, "ℹ️ Balas foto/stiker lalu kirim `.sticker`.")
        return
    try:
        data = await client.download_message_media(media)
    except Exception as e:
        await client.send_text(chat_jid, f"⚠️ Gagal ambil media: {e}")
        return
    webp = await asyncio.to_thread(_make_sticker_bytes, data)
    if not webp:
        await client.send_text(chat_jid, "⚠️ PIL tidak tersedia / gagal konversi.")
        return
    await client.send_sticker(chat_jid, webp, is_animated=(mtype == "sticker"))


async def _cmd_toimg(client, chat_jid, inner):
    mtype, media = _extract_media(inner)
    if mtype != "sticker":
        await client.send_text(chat_jid, "ℹ️ Balas *stiker* lalu kirim `.toimg`.")
        return
    try:
        data = await client.download_message_media(media)
    except Exception as e:
        await client.send_text(chat_jid, f"⚠️ Gagal ambil stiker: {e}")
        return
    try:
        from PIL import Image, ImageOps
        im = Image.open(BytesIO(data))
        im = ImageOps.exif_transpose(im)
        out = BytesIO()
        im.convert("RGBA").save(out, format="PNG")
        await client.send_image(chat_jid, out.getvalue(), mimetype="image/png")
    except Exception as e:
        await client.send_text(chat_jid, f"⚠️ Gagal konversi: {e}")


async def _cmd_dl(client, chat_jid, url):
    if not url:
        await client.send_text(
            chat_jid,
            "ℹ️ Contoh:\n`.dl https://youtu.be/xxx`\n"
            "`.dl a https://...` — audio saja\n"
            "`.dl p https://...` — gambar saja",
        )
        return
    want_audio = False
    want_photo = False
    url = url.strip()
    parts = url.split(maxsplit=1)
    if parts[0].lower() in ("a", "audio") and len(parts) > 1:
        want_audio = True
        url = parts[1].strip()
    elif parts[0].lower() in ("p", "photo", "img", "image") and len(parts) > 1:
        want_photo = True
        url = parts[1].strip()

    if not url.startswith(("http://", "https://")):
        await client.send_text(chat_jid, "⚠️ URL tidak valid.")
        return
    await client.send_text(chat_jid, "⬇️ Mendownload…")
    try:
        import yt_dlp
    except Exception:
        await client.send_text(chat_jid, "❌ yt-dlp tidak tersedia.")
        return

    dl_dir = BASE_DIR / "wabot" / "dl"
    dl_dir.mkdir(parents=True, exist_ok=True)
    outtmpl = str(dl_dir / "%(id)s.%(ext)s")
    opts = {
        "outtmpl": outtmpl,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "restrictfilenames": True,
        "retries": 2,
        "http_headers": {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"},
        "extractor_args": {
            "tiktok": {"api_hostname": ["api16-normal-c-useast1a.tiktok.com"]},
            "tiktokweb": {"api_hostname": ["api16-normal-c-useast1a.tiktok.com"]},
        },
    }
    if want_audio:
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}]
    elif want_photo:
        opts["format"] = "worst/worst[ext=webp]/best"
    else:
        opts["format"] = "bv*[height<=720]+ba/b[height<=720]/b"
        opts["merge_output_format"] = "mp4"

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
        fname = ydl.prepare_filename(info)
        if not Path(fname).exists():
            # cari file by id prefix
            hits = list(dl_dir.glob(f"{info.get('id','')}.*"))
            fname = str(hits[0]) if hits else None
        if not fname or not Path(fname).exists():
            await client.send_text(chat_jid, "⚠️ File tidak ditemukan setelah download.")
            return
    except Exception as e:
        await client.send_text(chat_jid, f"⚠️ Download gagal: {str(e)[:200]}")
        return

    fname = Path(fname)
    try:
        size_mb = fname.stat().st_size / (1024 * 1024)
        if size_mb > 60:
            await client.send_text(chat_jid, f"⚠️ Terlalu besar: {size_mb:.1f} MB.")
            fname.unlink(missing_ok=True)
            return
        title = (info.get("title") or info.get("id") or str(fname)).strip()
        if want_audio:
            await client.send_text(chat_jid, f"🎵 *{title}*\nMengirim audio…")
            await client.send_document_file(chat_jid, str(fname),
                                            caption=title[:200], filename=fname.name)
        else:
            ext = fname.suffix.lower().lstrip(".")
            if ext in ("png", "jpg", "jpeg", "webp", "gif") or want_photo:
                await client.send_text(chat_jid, f"🖼 *{title}*\nMengirim foto…")
                await client.send_image_file(chat_jid, str(fname), caption=title[:200])
            else:
                await client.send_text(chat_jid, f"🎬 *{title}*\nMengirim video…")
                await client.send_video_file(chat_jid, str(fname), caption=title[:200])
    except Exception as e:
        await client.send_text(chat_jid, f"⚠️ Gagal kirim media: {str(e)[:200]}")
    finally:
        fname.unlink(missing_ok=True)


async def _cmd_tagall(client, chat_jid, arg):
    if not _is_group(chat_jid):
        await client.send_text(chat_jid, "ℹ️ `.tagall` hanya utk grup.")
        return
    if not (arg.strip() or ""):
        arg = "Halo semua! 👋"
    try:
        meta = await client.socket.group_metadata(chat_jid)
    except Exception as e:
        await client.send_text(chat_jid, f"⚠️ Gagal ambil member: {e}")
        return
    parts = getattr(meta, "participants", None) or []
    mentions = []
    for p in parts:
        jid = getattr(p, "id", None) or ""
        if jid:
            mentions.append(jid)
    if not mentions:
        await client.send_text(chat_jid, "⚠️ Tidak ada member ditemukan.")
        return

    # Kirim extendedTextMessage dgn mentionedJid (mention real).
    try:
        from pyaileys.proto import WAProto_pb2 as proto
        import secrets
        msg = proto.Message()
        etm = msg.extendedTextMessage
        etm.text = f"{arg}\n" + " ".join(f"@{m.split('@')[0]}" for m in mentions[:30])
        for m in mentions[:30]:
            etm.contextInfo.mentionedJid.append(m)
        msg.messageContextInfo.messageSecret = secrets.token_bytes(32)
        await client._send_message(
            chat_jid, msg,
            stanza_type="text", enc_extra_attrs=None, fanout=True,
            include_phash=False, wait_ack=False, timeout_s=15,
        )
    except Exception as e:
        body = f"{arg}\n" + " ".join(f"@{m.split('@')[0]}" for m in mentions[:30])
        await client.send_text(chat_jid, body)


async def _cmd_bc(client, chat_jid, sender_jid, arg):
    if not _is_owner(sender_jid):
        await client.send_text(chat_jid, "⛔ Khusus owner.")
        return
    cfg = _load_config()
    targets = [_owner()]
    targets += [_cfg_jid(x) for x in cfg.get("users", [])]
    r = [t for t in targets if t and _jid_key(t) != _jid_key(chat_jid)]
    for t in r:
        try:
            await client.send_text(t, arg or "📢 Broadcast")
            await asyncio.sleep(1.5)
        except Exception as e:
            log.warning("bc ke %s gagal: %s", t, e)
    await client.send_text(chat_jid, f"📣 Broadcast dikirim ke {len(r)} tujuan.")


async def _cmd_sched(client, chat_jid, sender_jid, arg):
    if not _is_owner(sender_jid):
        await client.send_text(chat_jid, "⛔ Khusus owner.")
        return
    parts = arg.split(maxsplit=1)
    if len(parts) != 2:
        await client.send_text(chat_jid, "ℹ️ Contoh: `.sched 21:30 pesan malam`")
        return
    when, text_ = parts[0], parts[1]
    try:
        h, m = when.split(":")
        int(h), int(m)
    except Exception:
        await client.send_text(chat_jid, "⚠️ Format waktu: `HH:MM`")
        return
    cfg = _load_config()
    scheds = list(cfg.get("schedules", []))
    sid = int(time.time())
    scheds.append({"id": sid, "time": f"{int(h):02d}:{int(m):02d}",
                   "jid": chat_jid, "text": text_})
    cfg["schedules"] = scheds
    _save_config(cfg)
    await client.send_text(
        chat_jid, f"⏰ Terjadwal setiap hari jam {int(h):02d}:{int(m):02d}. ID: `{sid}`")


async def _cmd_schedlist(client, chat_jid):
    cfg = _load_config()
    scheds = cfg.get("schedules", []) or []
    if not scheds:
        await client.send_text(chat_jid, "ℹ️ Belum ada jadwal.")
        return
    body = "*Jadwal:*\n"
    for s in scheds:
        body += f"• `{s.get('id')}` {s.get('time')} → {s.get('jid')} : {s.get('text','')[:40]}\n"
    await client.send_text(chat_jid, body.strip())


async def _cmd_scheddel(client, chat_jid, sender_jid, arg):
    if not _is_owner(sender_jid):
        await client.send_text(chat_jid, "⛔ Khusus owner.")
        return
    cfg = _load_config()
    try:
        sid = int(arg)
    except Exception:
        await client.send_text(chat_jid, "ℹ️ Contoh: `.scheddel <id>` (lihat `.schedlist`)")
        return
    cfg["schedules"] = [s for s in cfg.get("schedules", []) if s.get("id") != sid]
    _save_config(cfg)
    await client.send_text(chat_jid, f"🗑 Jadwal `{sid}` dihapus.")


async def _cmd_ar(client, chat_jid, sender_jid, arg):
    if not _is_owner(sender_jid):
        await client.send_text(chat_jid, "⛔ Khusus owner.")
        return
    cfg = _load_config()
    ar = cfg.get("autoreply")
    if isinstance(ar, str):
        ar = {"on": bool(ar.strip()), "text": ar.strip(), "keywords": {}}
    ar = dict(ar) if isinstance(ar, dict) else {"on": False, "text": "", "keywords": {}}
    ar.setdefault("keywords", {})
    kw = ar.get("keywords") or {}
    arg = arg.strip()

    if not arg:
        ar["on"] = False
        ar["text"] = ""
        cfg["autoreply"] = ar
        _save_config(cfg)
        await client.send_text(chat_jid, "✅ Auto-reply dimatikan.")
        return

    low = arg.lower()
    if low.startswith("kw "):
        spec = arg[3:].strip()
        if ";" in spec:
            kata, balas = spec.split(";", 1)
            kw[kata.strip()] = balas.strip()
        else:
            if "|" in spec:
                kata, balas = spec.split("|", 1)
                kw[kata.strip()] = balas.strip()
            else:
                await client.send_text(chat_jid, "ℹ️ Contoh: `.ar kw halo; Hai juga!`")
                return
        ar["keywords"] = kw
        cfg["autoreply"] = ar
        _save_config(cfg)
        await client.send_text(chat_jid, f"✅ Keyword `{kata.strip()}` → \"{balas.strip()[:60]}\"")
        return
    if low == "list":
        if not kw:
            await client.send_text(chat_jid, "ℹ️ Belum ada keyword. `.ar kw kata; balasan`")
            return
        body = "*Auto-reply keyword:*\n"
        for k, v in kw.items():
            body += f"• `{k}` → \"{v[:50]}\"\n"
        body += f"\nDefault: \"{(ar.get('text') or '')[:50]}\""
        await client.send_text(chat_jid, body.strip())
        return
    if low.startswith("del "):
        k = arg[4:].strip()
        if k in kw:
            del kw[k]
            ar["keywords"] = kw
            cfg["autoreply"] = ar
            _save_config(cfg)
            await client.send_text(chat_jid, f"🗑 Keyword `{k}` dihapus.")
        else:
            await client.send_text(chat_jid, f"ℹ️ Keyword `{k}` tidak ada.")
        return

    ar["on"] = True
    ar["text"] = arg
    cfg["autoreply"] = ar
    _save_config(cfg)
    await client.send_text(chat_jid, f"✅ Auto-reply default aktif: \"{arg[:80]}\"")


async def _cmd_autoread(client, chat_jid, sender_jid, arg):
    if not _is_owner(sender_jid):
        await client.send_text(chat_jid, "⛔ Khusus owner.")
        return
    cfg = _load_config()
    val = arg.strip().lower()
    if val in ("on", "1", "true", "yes"):
        cfg["autoread"] = True
        _save_config(cfg)
        await client.send_text(chat_jid, "✅ Autoread aktif.")
    elif val in ("off", "0", "false", "no"):
        cfg["autoread"] = False
        _save_config(cfg)
        await client.send_text(chat_jid, "✅ Autoread dimatikan.")
    elif not val:
        await client.send_text(chat_jid, f"ℹ️ Autoread: `{'ON' if cfg.get('autoread') else 'OFF'}`")
    else:
        await client.send_text(chat_jid, "ℹ️ Contoh: `.autoread on` / `.autoread off`")


async def _http_get_json(url: str, timeout: float = 15) -> dict:
    import urllib.request
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/125.0 Safari/537.36"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


async def _cmd_cuaca(client, chat_jid, arg):
    if not arg:
        await client.send_text(chat_jid, "ℹ️ Contoh: `.cuaca mataram`")
        return
    try:
        q = urllib.parse.quote(arg.strip())
        geo = await _http_get_json(
            f"https://geocoding-api.open-meteo.com/v1/search?name={q}&count=1&language=id"
        )
        hits = geo.get("results") or []
        if not hits:
            await client.send_text(chat_jid, f"⚠️ Kota `{arg}` tidak ditemukan.")
            return
        lat = hits[0]["latitude"]
        lon = hits[0]["longitude"]
        nama = f"{hits[0].get('name','')}, {hits[0].get('admin1') or ''} {hits[0].get('country','')}".strip()
        wx = await _http_get_json(
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m,"
            "apparent_temperature,is_day,precipitation,weather_code,wind_speed_10m"
        )
        cur = wx.get("current") or {}
        code = cur.get("weather_code", 0)
        desk = {
            0: "Cerah", 1: "Sebagian cerah", 2: "Berawan", 3: "Mendung",
            45: "Kabut", 48: "Kabut dingin", 51: "Gerimis ringan", 53: "Gerimis",
            55: "Gerimis deras", 61: "Hujan ringan", 63: "Hujan", 65: "Hujan deras",
            71: "Salju ringan", 73: "Salju", 75: "Salju deras", 95: "Badai petir",
            96: "Badai petir + hujan", 99: "Badai petir + hujan lebat",
        }.get(int(code or 0), f"Kode {code}")
        body = (
            f"*Cuaca {nama}*\n\n"
            f"🌡 Suhu: {cur.get('temperature_2m')}°C (terasa {cur.get('apparent_temperature')}°C)\n"
            f"💧 Kelembaban: {cur.get('relative_humidity_2m')}%\n"
            f"🌤 Kondisi: {desk}\n"
            f"💨 Angin: {cur.get('wind_speed_10m')} km/j"
        )
        await client.send_text(chat_jid, body)
    except Exception as e:
        await client.send_text(chat_jid, f"⚠️ Gagal: {str(e)[:120]}")


async def _cmd_tr(client, chat_jid, arg):
    parts = arg.split(maxsplit=1)
    if len(parts) != 2:
        await client.send_text(chat_jid, "ℹ️ Contoh: `.tr en apa kabar`")
        return
    lang, teks = parts[0].strip(), parts[1].strip()
    try:
        url = ("https://translate.googleapis.com/translate_a/single"
               f"?client=gtx&sl=auto&tl={urllib.parse.quote(lang)}&dt=t&q={urllib.parse.quote(teks)}")
        body = await _http_get_json(url)
        hasil = "".join(part[0] for part in body[0] if part and part[0])
        await client.send_text(chat_jid, hasil or f"⚠️ Bahasa `{lang}` tidak dikenal.")
    except Exception as e:
        await client.send_text(chat_jid, f"⚠️ Gagal: {str(e)[:120]}")


async def _cmd_qr(client, chat_jid, arg):
    if not arg:
        await client.send_text(chat_jid, "ℹ️ Contoh: `.qr https://example.com`")
        return
    try:
        import segno
        out = BytesIO()
        segno.make(arg[:1000], error="m").save(out, kind="png", scale=8, border=2)
        await client.send_image(chat_jid, out.getvalue(), mimetype="image/png",
                                caption=f"QR: {arg[:80]}")
    except Exception as e:
        await client.send_text(chat_jid, f"⚠️ Gagal: {str(e)[:120]}")


async def _cmd_short(client, chat_jid, arg):
    url = arg.strip()
    if not url.startswith(("http://", "https://")):
        await client.send_text(chat_jid, "ℹ️ Contoh: `.short https://example.com/panjang`")
        return
    try:
        short = await _http_get_json(
            "https://is.gd/create.php?format=json&url=" + urllib.parse.quote(url)
        )
        if isinstance(short, dict) and short.get("shorturl"):
            await client.send_text(chat_jid, f"🔗 *{short['shorturl']}*")
        else:
            await client.send_text(chat_jid, f"⚠️ {short.get('errormessage', 'Gagal')}")
    except Exception as e:
        await client.send_text(chat_jid, f"⚠️ Gagal: {str(e)[:120]}")


def _safe_calc(expr: str):
    tree = ast.parse(expr, mode="eval")
    if not isinstance(tree, ast.Expression):
        raise ValueError("ekspresi tidak valid")
    node = tree.body
    allowed_ops = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow, ast.USub, ast.UAdd)
    allowed_nodes = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant,
                     ast.Name, ast.Load, ast.Compare) | allowed_ops
    if not isinstance(node, (ast.BinOp, ast.UnaryOp, ast.Constant, ast.Name)):
        raise ValueError("ekspresi tidak valid")
    for sub in ast.walk(node):
        if isinstance(sub, (ast.BinOp, ast.UnaryOp, ast.Compare)):
            for child in ast.iter_child_nodes(sub):
                pass
            if isinstance(sub, (ast.BinOp, ast.UnaryOp)) and not isinstance(sub.op, allowed_ops):
                raise ValueError("operator tidak valid")
            for ch in ast.walk(sub):
                if isinstance(ch, ast.Name) and ch.id not in ("e", "pi"):
                    raise ValueError(f"variabel tak dikenal: {ch.id}")
        elif isinstance(sub, ast.Name) and sub.id not in ("e", "pi"):
            raise ValueError(f"variabel tak dikenal: {sub.id}")
    ns = {"e": 2.718281828459045, "pi": 3.141592653589793}
    return eval(compile(tree, "<calc>", "eval"), {"__builtins__": {}}, ns)


async def _cmd_calc(client, chat_jid, arg):
    if not arg:
        await client.send_text(chat_jid, "ℹ️ Contoh: `.calc (12+7)*3`")
        return
    try:
        r = _safe_calc(arg)
        await client.send_text(chat_jid, f"🧮 `{arg}` = `{r:g}`")
    except Exception as e:
        await client.send_text(chat_jid, f"⚠️ Gagal: {str(e)[:120]}")


async def _cmd_random(client, chat_jid, arg):
    parts = arg.split()
    try:
        if len(parts) == 2:
            lo, hi = int(parts[0]), int(parts[1])
        elif len(parts) == 1:
            lo, hi = 0, int(parts[0])
        else:
            lo, hi = 0, 100
        if lo > hi:
            lo, hi = hi, lo
        await client.send_text(chat_jid, f"🎲 {random.randint(lo, hi)}")
    except Exception:
        await client.send_text(chat_jid, "ℹ️ Contoh: `.random 1 100`")


async def _cmd_yt(client, chat_jid, arg):
    if not arg:
        await client.send_text(chat_jid, "ℹ️ Contoh: `.yt lofi study`")
        return
    try:
        import yt_dlp
        opts = {"quiet": True, "no_warnings": True, "noplaylist": True,
                "noprogress": True, "skip_download": True,
                "extractor_args": {
                    "tiktok": {"api_hostname": ["api16-normal-c-useast1a.tiktok.com"]},
                    "tiktokweb": {"api_hostname": ["api16-normal-c-useast1a.tiktok.com"]},
                }}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch5:{arg}", download=False)
        entries = [e for e in (info.get("entries") or []) if e]
        if not entries:
            await client.send_text(chat_jid, "⚠️ Tidak ada hasil.")
            return
        body = f"*Hasil untuk \"{arg}\":*\n\n"
        for i, e in enumerate(entries[:5], 1):
            title = (e.get("title") or "?").strip()
            dur = e.get("duration")
            dur_s = f"{dur // 60}:{dur % 60:02d} m" if dur else "?"
            chan = (e.get("channel") or "?").strip()
            body += f"{i}. {title}\n   ⏱ {dur_s} · {chan}\n   {e.get('webpage_url')}\n\n"
        await client.send_text(chat_jid, body.strip()[:4000])
    except Exception as e:
        await client.send_text(chat_jid, f"⚠️ Gagal: {str(e)[:150]}")


async def _cmd_tts(client, chat_jid, arg):
    if not arg:
        await client.send_text(chat_jid, "ℹ️ Contoh: `.tts halo selamat pagi` (`.tts en hello`)")
        return
    teks = arg.strip()
    lang = "id"
    parts = teks.split(maxsplit=1)
    if len(parts) == 2 and parts[0].lower() in ("id", "en", "ar", "zh", "ja", "ko", "es", "fr", "de", "hi"):
        lang, teks = parts[0].lower(), parts[1].strip()
    try:
        url = ("https://translate.googleapis.com/translate_tts"
               f"?ie=UTF-8&tl={lang}&client=tw-ob&q={urllib.parse.quote(teks[:400])}")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read()
        if not data:
            raise ValueError("respon kosong (biasanya teks terlalu panjang)")
        tmp = BASE_DIR / "wabot" / "tts-s.mp3"
        tmp.write_bytes(data)
        await client.send_document_file(chat_jid, str(tmp),
                                        filename=f"tts-{lang}.mp3",
                                        mimetype="audio/mpeg",
                                        caption=f"🗣 {teks[:80]}")
        tmp.unlink(missing_ok=True)
    except Exception as e:
        await client.send_text(chat_jid, f"⚠️ Gagal: {str(e)[:120]}")


async def _cmd_music(client, chat_jid, arg):
    if not arg:
        await client.send_text(chat_jid, "ℹ️ Contoh: `.music marshmello alone`")
        return
    await client.send_text(chat_jid, "🎵 Mencari audio…")
    dl_dir = BASE_DIR / "wabot" / "dl"
    dl_dir.mkdir(parents=True, exist_ok=True)
    try:
        import yt_dlp
        opts = {
            "outtmpl": str(dl_dir / "music-%(id)s.%(ext)s"),
            "format": "bestaudio/best",
            "noplaylist": True, "quiet": True, "no_warnings": True,
            "noprogress": True, "retries": 2,
            "extractor_args": {
                "tiktok": {"api_hostname": ["api16-normal-c-useast1a.tiktok.com"]},
                "tiktokweb": {"api_hostname": ["api16-normal-c-useast1a.tiktok.com"]},
            },
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch1:{arg}", download=True)
        fid = info.get("id", "")
        hits = list(dl_dir.glob(f"music-{fid}.*"))
        if not hits:
            await client.send_text(chat_jid, "⚠️ File tidak ditemukan.")
            return
        f = hits[0]
        title = (info.get("title") or "?").strip()
        await client.send_text(chat_jid, f"🎵 *{title}*\nMengirim audio…")
        mt = "audio/webm" if f.suffix.lower() == ".webm" else "audio/mpeg"
        await client.send_document_file(chat_jid, str(f), mimetype=mt, filename=f.name,
                                        caption=title[:200])
        f.unlink(missing_ok=True)
    except Exception as e:
        await client.send_text(chat_jid, f"⚠️ Gagal: {str(e)[:150]}")


async def _cmd_remind(client, chat_jid, sender_jid, arg):
    if not _is_owner(sender_jid):
        await client.send_text(chat_jid, "⛔ Khusus owner.")
        return
    parts = arg.split(maxsplit=1)
    if len(parts) != 2:
        await client.send_text(chat_jid, "ℹ️ Contoh: `.remind 21:00 minum obat`")
        return
    when, teks = parts[0].strip(), parts[1].strip()
    try:
        h, m = when.split(":")
        int(h), int(m)
        tipe = "daily"
    except Exception:
        try:
            delta = int(when)
            if delta <= 0:
                raise ValueError
            target = int(time.time()) + delta * 60
            wait_s = delta * 60
            tipe = "once"
        except Exception:
            await client.send_text(chat_jid, "⚠️ Waktu: `HH:MM` atau menit angka (cth 30).")
            return
    cfg = _load_config()
    rems = list(cfg.get("reminders", []))
    rid = int(time.time())
    rems.append({"id": rid, "jid": chat_jid, "text": teks, "type": tipe,
                 "time": f"{int(h):02d}:{int(m):02d}" if tipe == "daily" else None,
                 "wait_s": wait_s if tipe == "once" else None,
                 "target": target if tipe == "once" else None})
    cfg["reminders"] = rems
    _save_config(cfg)
    label = f"jam {int(h):02d}:{int(m):02d}" if tipe == "daily" else f"{wait_s // 60} menit lagi"
    await client.send_text(chat_jid, f"⏰ Pengingat di-{label}: \"{teks[:60]}\". ID `{rid}`")


async def _cmd_kick(client, chat_jid, sender_jid, arg):
    if not _is_owner(sender_jid):
        await client.send_text(chat_jid, "⛔ Khusus owner.")
        return
    jid = _norm_number(arg)
    ok = await _group_participants_update(client, chat_jid, "remove", jid)
    await client.send_text(chat_jid, f"👢 `{jid}` di-kick.\n{'✅ OK' if ok else '⚠️ Gagal/butuh jadi admin pengajar.'}")


async def _cmd_addmember(client, chat_jid, sender_jid, arg):
    if not _is_owner(sender_jid):
        await client.send_text(chat_jid, "⛔ Khusus owner.")
        return
    jid = _norm_number(arg)
    ok = await _group_participants_update(client, chat_jid, "add", jid)
    await client.send_text(chat_jid, f"➕ `{jid}` ditambahkan.\n{'✅ OK' if ok else '⚠️ Gagal/butuh jd admin.'}")


async def _cmd_antileave(client, chat_jid, sender_jid):
    if not _is_owner(sender_jid):
        await client.send_text(chat_jid, "⛔ Khusus owner.")
        return
    if not _is_group(chat_jid):
        await client.send_text(chat_jid, "ℹ️ Jalankan di dalam grup.")
        return
    cfg = _load_config()
    anti = cfg.setdefault("antimod", {})
    key = _jid_key(chat_jid)
    cur = anti.get(key, {})
    cur["leave"] = not cur.get("leave")
    anti[key] = cur
    cfg["antimod"] = anti
    _save_config(cfg)
    st = "ON" if cur["leave"] else "OFF"
    await client.send_text(chat_jid, f"🛡 Anti-leave: `{st}` (kick member yg keluar dlm 5 menit lalu masuk kembali)")


async def _cmd_antijoin(client, chat_jid, sender_jid):
    if not _is_owner(sender_jid):
        await client.send_text(chat_jid, "⛔ Khusus owner.")
        return
    if not _is_group(chat_jid):
        await client.send_text(chat_jid, "ℹ️ Jalankan di dalam grup.")
        return
    cfg = _load_config()
    anti = cfg.setdefault("antimod", {})
    key = _jid_key(chat_jid)
    cur = anti.get(key, {})
    cur["join"] = not cur.get("join")
    anti[key] = cur
    cfg["antimod"] = anti
    _save_config(cfg)
    st = "ON" if cur["join"] else "OFF"
    await client.send_text(chat_jid, f"🛡 Anti-join: `{st}` (auto-kick member baru yg tidak punya akses)")


async def _cmd_sholat(client, chat_jid, arg):
    if not arg:
        await client.send_text(chat_jid, "ℹ️ Contoh: `.sholat mataram`")
        return
    try:
        kota = urllib.parse.quote(arg.strip())
        body = await _http_get_json(
            "https://api.aladhan.com/v1/timingsByCity"
            f"?city={kota}&country=ID&method=20"
        )
        data = body.get("data") or {}
        date = data.get("date") or {}
        timings = data.get("timings") or {}
        if not timings:
            await client.send_text(chat_jid, f"⚠️ Kota `{arg}` tidak ditemukan.")
            return
        meta = data.get("meta") or {}
        greg = (date.get("gregorian") or {}).get("date") or "?"
        hijr = (date.get("hijri") or {}).get("date") or "?"
        tz = (meta.get("timezone") or "?").strip()
        txt = (
            f"*Jadwal Sholat — {arg.title()}*\n"
            f"📅 {greg} ({hijr})\n\n"
            f"🌅 Imsak: {timings.get('Imsak')}\n"
            f"🌇 Subuh: {timings.get('Fajr')}\n"
            f"☀️ Dhuha: {timings.get('Sunrise')}\n"
            f"🕛 Dzuhur: {timings.get('Dhuhr')}\n"
            f"🌆 Ashar: {timings.get('Asr')}\n"
            f"🌄 Maghrib: {timings.get('Maghrib')}\n"
            f"🌃 Isya: {timings.get('Isha')}\n\n🧭 Waktu: {tz}"
        )
        await client.send_text(chat_jid, txt)
    except Exception as e:
        await client.send_text(chat_jid, f"⚠️ Gagal: {str(e)[:120]}")


async def _cmd_hijri(client, chat_jid):
    try:
        body = await _http_get_json("https://api.aladhan.com/v1/gToH")
        data = body.get("data") or {}
        hijr = data.get("hijri") or {}
        weeks = hijr.get("weekday") or {}
        months = hijr.get("month") or {}
        await client.send_text(
            chat_jid,
            f"📅 *Hari ini:* {weeks.get('ar')}/{weeks.get('en')}\n"
            f"🗓 Tanggal: {hijr.get('day')} {months.get('en')} {hijr.get('year')} H\n"
            f"🕌 Lua: {hijr.get('designation')}",
        )
    except Exception as e:
        await client.send_text(chat_jid, f"⚠️ Gagal: {str(e)[:120]}")


async def _cmd_qibla(client, chat_jid, arg):
    if not arg:
        await client.send_text(chat_jid, "ℹ️ Contoh: `.qibla jakarta`")
        return
    try:
        q = urllib.parse.quote(arg.strip())
        geo = await _http_get_json(
            f"https://geocoding-api.open-meteo.com/v1/search?name={q}&count=1&language=id"
        )
        hits = geo.get("results") or []
        if not hits:
            await client.send_text(chat_jid, f"⚠️ Kota `{arg}` tidak ditemukan.")
            return
        lat, lon = hits[0]["latitude"], hits[0]["longitude"]
        # Arab Saudi Kaaba: 21.4225, 39.8262
        import math
        dLon = math.radians(39.8262 - lon)
        y = math.sin(dLon)
        x = (math.cos(math.radians(lat)) * math.tan(math.radians(21.4225))
             - math.sin(math.radians(lat)) * math.cos(dLon))
        bearing = (math.degrees(math.atan2(y, x)) + 360) % 360
        arah = ["Utara", "Timur Laut", "Timur", "Tenggara", "Selatan",
                "Barat Daya", "Barat", "Barat Laut"]
        idx = int((bearing / 45) + 0.5) % 8
        nama = f"{hits[0].get('name','')}, {hits[0].get('admin1') or ''}".strip()
        await client.send_text(
            chat_jid,
            f"🕋 *Arah Kiblat — {nama}*\n\n"
            f"🧭 {bearing:.1f}° dari utara ({arah[idx]})\n"
            f"📐 Jarak ~1211 km menuju Kakbah (Makkah)",
        )
    except Exception as e:
        await client.send_text(chat_jid, f"⚠️ Gagal: {str(e)[:120]}")


async def _cmd_hadits(client, chat_jid, arg):
    kits = {
        "bukhari": "bukhari", "muslim": "muslim", "abudawud": "abudawud",
        "abu-daud": "abudawud", "abudawood": "abudawud", "tirmidzi": "tirmidhi",
        "tirmidhi": "tirmidhi", "nasai": "nasai", "nasa'i": "nasai",
        "ibnumajah": "ibnmajah", "ibnu-majah": "ibnmajah", "ibn majah": "ibnmajah",
        "ahmad": "muslim", "malik": "malik", "darimi": "muslim",
        "nawawi": "nawawi", "40": "nawawi", "qudsi": "qudsi",
    }
    kit = kits.get(arg.strip().lower().replace(" ", " "), "bukhari")
    try:
        body = await _http_get_json(
            "https://ummahapi.com/api/hadith/random?collection=" + urllib.parse.quote(kit)
        )
        data = body.get("data") or {}
        if not data:
            await client.send_text(chat_jid, "⚠️ Tidak ada hadits.")
            return
        nama = (data.get("collection_name") or kit.title()).strip()
        teks = data.get("english") or data.get("arabic") or ""
        if not teks:
            await client.send_text(chat_jid, "⚠️ Hadits kosong.")
            return
        terjemah = f"\n\n*Terjemah Indonesia:* {teks_ar}" if (teks_ar := data.get("arabic")) else ""
        await client.send_text(
            chat_jid,
            f"*Hadits {nama}*\n\n{teks[:1400]}{terjemah}\n\n"
            f"• No {data.get('hadithnumber')} · {data.get('grade') or ''}".rstrip(),
        )
    except Exception as e:
        await client.send_text(chat_jid, f"⚠️ Gagal: {str(e)[:120]}")


async def _cmd_gempa(client, chat_jid):
    try:
        body = await _http_get_json(
            "https://data.bmkg.go.id/DataMKG/TEWS/autogempa.json"
        )
        ins = (body.get("Infogempa") or {}).get("gempa") or {}
        if not ins:
            await client.send_text(chat_jid, "⚠️ Tidak ada data gempa.")
            return
        def f(k): return f"{ins.get(k) or '-'}".strip()
        waktu = f"{f('Tanggal')} {f('Jam')}".strip()
        await client.send_text(
            chat_jid,
            f"*⚠️ Gempa Terkini (BMKG)*\n\n"
            f"🕐 Waktu: {waktu}\n"
            f"📍 Wilayah: {f('Wilayah')}\n"
            f"📏 Magnitudo: {f('Magnitude')}\n"
            f"🎚 Kedalaman: {f('Kedalaman')}\n"
            f"🌐 Lintang/Bujur: {f('Lintang')}, {f('Bujur')}\n"
            f"ℹ️ {f('Potensi')}",
        )
    except Exception as e:
        await client.send_text(chat_jid, f"⚠️ Gagal: {str(e)[:150]}")


async def _cmd_wiki(client, chat_jid, arg):
    if not arg:
        await client.send_text(chat_jid, "ℹ️ Contoh: `.wiki isekai`")
        return
    try:
        q = urllib.parse.quote(arg.strip())
        body = await _http_get_json(
            "https://id.wikipedia.org/api/rest_v1/page/summary/" + q
        )
        if not body.get("extract"):
            await client.send_text(chat_jid, f"⚠️ Topik `{arg}` tidak ditemukan.")
            return
        link = body.get("content_urls", {}).get("desktop", {}).get("page", "")
        await client.send_text(
            chat_jid,
            f"*{body.get('title') or arg}*\n\n{body['extract'][:1200]}\n\n{link}",
        )
    except Exception as e:
        await client.send_text(chat_jid, f"⚠️ Gagal: {str(e)[:120]}")


async def _cmd_lirik(client, chat_jid, arg):
    if not arg:
        await client.send_text(chat_jid, "ℹ️ Contoh: `.lirik pelan pelan saja`")
        return
    try:
        body = await _http_get_json(
            "https://lrclib.net/api/search?q=" + urllib.parse.quote(arg.strip())
        )
        if not isinstance(body, list) or not body:
            await client.send_text(chat_jid, f"⚠️ Lirik `{arg}` tidak ditemukan.")
            return
        best = body[0]
        lirik = best.get("plainLyrics") or ""
        if not lirik:
            await client.send_text(chat_jid, f"⚠️ Lirik `{arg}` tidak ditemukan.")
            return
        judul = (best.get("trackName") or arg).title()
        artis = best.get("artistName") or ""
        await client.send_text(
            chat_jid,
            f"*🎵 {judul} — {artis}*\n\n{lirik[:1800]}\n\nvia LRCLIB",
        )
    except Exception as e:
        await client.send_text(chat_jid, f"⚠️ Gagal: {str(e)[:120]}")


async def _cmd_lokasi(client, chat_jid, arg):
    import re
    m = re.match(r"^\s*([-\d.]+)\s*[,;]\s*([-\d.]+)\s+(.+)$", arg)
    if not m:
        await client.send_text(chat_jid, "ℹ️ Contoh: `.lokasi -8.58,116.11 Mataram`")
        return
    lat, lon, label = float(m.group(1)), float(m.group(2)), m.group(3).strip()
    try:
        await client.send_location(chat_jid, latitude=lat, longitude=lon, name=label)
        await client.send_text(chat_jid, f"📍 Lokasi dikirim: {label}")
    except Exception as e:
        await client.send_text(chat_jid, f"⚠️ Gagal: {str(e)[:120]}")


async def _cmd_kontak(client, chat_jid, arg):
    parts = arg.split()
    if len(parts) < 1:
        await client.send_text(chat_jid, "ℹ️ Contoh: `.kontak 628123456789 Nama`")
        return
    nomor = _norm_number(parts[0])
    if not nomor:
        await client.send_text(chat_jid, "⚠️ Nomor tidak valid.")
        return
    nama = " ".join(parts[1:]) or nomor.split("@")[0]
    vcard = (
        "BEGIN:VCARD\nVERSION:3.0\n"
        f"FN:{nama}\n"
        f"N:{nama};;;;\n"
        f"TEL;TYPE=CELL;VOICE;waid={nomor.split('@')[0]}:+{nomor.split('@')[0]}\n"
        "ORGANIZATION:Userbot\n"
        "END:VCARD"
    )
    try:
        await client.send_contact(chat_jid, display_name=nama, vcard=vcard)
        await client.send_text(chat_jid, f"👤 Kartu kontak *{nama}* terkirim.")
    except Exception as e:
        await client.send_text(chat_jid, f"⚠️ Gagal: {str(e)[:120]}")


async def _cmd_poll(client, chat_jid, arg):
    if "|" not in arg:
        await client.send_text(chat_jid, "ℹ️ Contoh: `.poll Siapa bestie-mu? | A | B | C`")
        return
    parts = [p.strip() for p in arg.split("|")]
    if len(parts) < 2:
        await client.send_text(chat_jid, "ℹ️ Perlu minimal 2 pilihan.")
        return
    soal = parts[0]
    opsi = [p for p in parts[1:] if p][:12]
    if len(opsi) < 2:
        await client.send_text(chat_jid, "ℹ️ Perlu minimal 2 pilihan.")
        return
    try:
        import secrets
        from pyaileys.proto import WAProto_pb2 as proto
        msg = proto.Message()
        msg.messageContextInfo.messageSecret = secrets.token_bytes(32)
        poll = msg.pollCreationMessage
        poll.name = soal[:1024]
        op_objs = []
        for o in opsi[:12]:
            op = proto.Message.PollCreationMessage.Option()
            op.optionName = o[:100]
            op_objs.append(op)
        poll.options.extend(op_objs)
        poll.selectableOptionsCount = len(op_objs)
        await client._send_message(
            chat_jid,
            msg,
            stanza_type="poll",
            enc_extra_attrs=None,
            fanout=True,
            include_phash=False,
            wait_ack=False,
            timeout_s=15.0,
        )
        await client.send_text(chat_jid, f"🗳 Poll dibuat: *{soal[:60]}* ({len(op_objs)} pilihan)")
    except Exception as e:
        await client.send_text(chat_jid, f"⚠️ Gagal: {str(e)[:150]}")


async def _cmd_stext(client, chat_jid, arg):
    if not arg:
        await client.send_text(chat_jid, "ℹ️ Contoh: `.stext halo bro`")
        return
    try:
        from PIL import Image, ImageDraw, ImageFont
        teks = arg.strip()[:200]
        lines = []
        cur = ""
        for w in teks.split():
            if len(cur) + len(w) + 1 > 24:
                lines.append(cur)
                cur = w
            else:
                cur = f"{cur} {w}".strip()
        if cur:
            lines.append(cur)
        lines = lines[:8] or [" "]
        pad = 50
        fnt = ImageFont.load_default()
        img = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        # citra teks dua baris per blok
        step = 512 // (len(lines) + 1)
        for i, ln in enumerate(lines, 1):
            bbox = d.textbbox((0, 0), ln, font=fnt)
            tw = bbox[2] - bbox[0]
            d.text(((512 - tw) / 2, i * step - 12), ln, font=fnt, fill=(255, 255, 255, 255))
        out = BytesIO()
        img.save(out, format="WEBP", quality=95)
        await client.send_sticker(chat_jid, out.getvalue())
    except Exception as e:
        await client.send_text(chat_jid, f"⚠️ Gagal: {str(e)[:120]}")


async def _cmd_quotes(client, chat_jid):
    try:
        body = await _http_get_json("https://zenquotes.io/api/random")
        if isinstance(body, list) and body:
            q = body[0]
            await client.send_text(chat_jid, f"*{q.get('q')}*\n\n— {q.get('a')}")
        else:
            await client.send_text(chat_jid, "⚠️ Gagal ambil quotes.")
    except Exception as e:
        await client.send_text(chat_jid, f"⚠️ Gagal: {str(e)[:120]}")


CERITA_TERPILIH = [
    # (judul, isi)
    ("Pagi di Kampung", "Udara pagi masih dingin ketika Rara membuka jendela kamarnya. Di depan rumah, ayam-ayam tetangga sudah mulai berkokok bergantian. Ia menarik napas dalam-dalam, menatap sawah yang mulai menghijau. \"Semoga hari ini bermanfaat,\" gumamnya. Dan benar, hari itu ia bertemu kakek tua yang menawarkan segelas teh hangat, lalu menemaninya menunggu bus di pinggir jalan. Hal kecil, tapi cukup menghangatkan hati sepanjang hari."),
    ("Topi Merah Ibu", "Budi menatap topi merah tua di sudut lemari. Topi itu selalu dipakai ibunya saat ke pasar. Hari ini, ulang tahun ibunya yang ke-50, dan Budi tidak punya hadiah apa pun. Ia mengambil kertas bekas, menggambar topi merah, lalu menulis: 'Terima kasih sudah jadi ibu terbaik.' Ibunya tersenyum sambil memeluknya. Sesederhana itu cinta ditunjukkan—tanpa harga, tanpa perlu dibeli."),
    ("Hujan di Stasiun", "Hujan deras mengguyur stasiun. Sari menunggu kereta terakhir pulang ke rumah orang tuanya di pedalaman. Di bangku sebelah, seorang anak kecil berbagi payung dengan neneknya. Sari teringat pesan ibunya: 'Kalau sedih, pulanglah.' Kereta datang, dan saat gerbong terbuka, ia melihat ayahnya sudah menunggu di balik gerbang. Hujan pun terasa hangat."),
    ("Kucing dan Penjual Bakso", "Pak Umar berjualan bakso keliling setiap sore. Seekor kucing belang sering menunggu di depan gerbangnya. Suatu hari hujan deras, kucing itu bersembunyi di gerobak. Pak Umar membiarkannya, bahkan memberinya bakso hangat tanpa sambal. Sejak itu, kucing itu selalu menemani, dan pelanggan mulai datang lebih banyak—tertawa melihat kucing yang duduk manis di gerobak bakso."),
    ("Lampu Kuning", "Di ujung gang, ada lampu kuning yang menyala setiap malam. Awa tinggal di rumah nomor 5, dan setiap pulang malam, lampu itu selalu menyala—menjaga langkahnya dari kucing-kucing yang tidur di jalan. Suatu malam lampu itu padam. Awa mengetuk rumah nomor 3, rumah Bu Ning, yang ternyata sedang sakit. \"Bu, boleh saya perbaiki lampunya?\" tanyanya. Sejak itu, mereka jadi tetangga yang saling menjaga."),
    ("Nasihat Kakek Nelayan", "Kakeknya adalah nelayan tua yang tak pernah punya kapal besar. \"Yang penting bukan besar kapalnya, tapi keikhlasan melautnya,\" katanya sambil memperbaiki jaring. Ilham muda menganggapnya klise sampai ia dewasa. Ketika gagal kerja di kota, ia pulang dan melihat kakeknya masih tersenyum di tepi pantai. Ilham ikut melaut keesokan harinya. Dalam sunyi laut, ia menemukan ketenangan yang tak pernah ia temukan di kota."),
]


async def _cmd_cerpen(client, chat_jid):
    judul, isi = random.choice(CERITA_TERPILIH)
    await client.send_text(chat_jid, f"*{judul}*\n\n{isi}")


PANUTAN_TERPILIH = [
   ("Jalan-jalan ke kota Malang", "Jangan lupa beli cendol.\nMakan sambil lihat awan menggantung,\nSemoga senyummu selalu terdengar.",),
    ("Pergi ke pasar beli ikan", "Ikan segar di dalam keranjang.\nKalau kamu lagi bingung dan gelisah,\nIngat selalu, ada yang sayang.",),
    ("Duduk santai di bawah pohon", "Melihat bukit di kejauhan.\nJangan risau tentang hari esok,\nNikmati saja hari yang berjalan.",),
    ("Naik becak keliling kota", "Panas terik ditimpa mentari.\nTinggalkan air mata yang tersisa,\nSemoga bahagia selalu menghampiri.",),
    ("Ke sawah membawa cangkul", "Menanam padi di musim hujan.\nHidup ini memang sulit dan rumit,\nTapi ibu selalu berdoa untukmu.",),
    ("Berjalan sambil menimba ilmu", "Hari terkenang masa sekolah.\nPegang teguh mimpimu yang satu,\nRaih cita setinggi bintang jelita.",),
]


async def _cmd_pantun(client, chat_jid):
    isi = random.choice(PANUTAN_TERPILIH)[0]
    await client.send_text(chat_jid, f"🪷 *Pantun*\n\n{isi}")


async def _cmd_kurs(client, chat_jid, arg):
    cur = arg.strip().upper().replace(" ", "")
    if not cur or not cur.isalpha():
        await client.send_text(chat_jid, "ℹ️ Contoh: `.usd 100` atau `.kurs 100 usd`")
        return
    try:
        import re
        mt = re.match(r"^([A-Za-z]{3})[-\s]?([\d.]+)$", cur) or \
             re.match(r"^([\d.]+)[-\s]?([A-Za-z]{3})$", cur)
        if mt:
            g = mt.groups()
            ccy, amt = (g[0].upper(), float(g[1])) if g[0].isalpha() else (g[1].upper(), float(g[0]))
        else:
            ccy, amt = cur, 1.0
        body = await _http_get_json("https://open.er-api.com/v6/latest/USD")
        rates = body.get("rates") or {}
        usd = rates.get("USD", 1.0)
        rate = rates.get(ccy)
        if not rate:
            await client.send_text(chat_jid, f"⚠️ Mata uang `{ccy}` tidak dikenal.")
            return
        val = amt * rate
        await client.send_text(chat_jid, f"💱 *{amt:g} {ccy}* = {val:,.2f} USD\n💰 1 USD = {rate} {ccy}")
    except Exception as e:
        await client.send_text(chat_jid, f"⚠️ Gagal: {str(e)[:120]}")


async def _cmd_infogrup(client, chat_jid):
    if not _is_group(chat_jid):
        await client.send_text(chat_jid, "ℹ️ Jalankan di dalam grup.")
        return
    try:
        meta = await client.socket.group_metadata(chat_jid)
        subject = meta.subject or chat_jid
        parts = meta.participants or []
        admins = [p for p in parts if p.admin]
        admin_label = "\n".join(f"• {p.phone_number or p.id}" for p in admins[:15]) or "(tidak ada)"
        msg = (f"*Grup: {subject}*\n\n"
               f"👥 Anggota: {len(parts)}\n"
               f"🛡 Admin ({len(admins)}):\n{admin_label}\n"
               f"🧬 Addressing: {meta.addressing_mode}")
        if meta.ephemeral_duration:
            msg += f"\n⏳ Pesan sementara: {meta.ephemeral_duration} detik"
        await client.send_text(chat_jid, msg)
    except Exception as e:
        await client.send_text(chat_jid, f"⚠️ Gagal: {str(e)[:120]}")


async def _cmd_listgrup(client, chat_jid):
    try:
        cfg = _load_config()
        groups = cfg.get("groups", []) or []
        if not groups:
            await client.send_text(chat_jid, "ℹ️ Belum ada grup diizinkan. Ketik `.allowgroup` di grup.")
            return
        body = "*Grup diizinkan:*\n"
        for g in groups:
            nama = ""
            try:
                nama = await client.resolve_group_name(g) or ""
            except Exception:
                pass
            body += f"• {nama or g}\n  `{g}`\n"
        await client.send_text(chat_jid, body.strip())
    except Exception as e:
        await client.send_text(chat_jid, f"⚠️ Gagal: {str(e)[:120]}")


# ==================== SCHEDULED MESSAGES ====================

async def _sched_loop(client, stop: asyncio.Event):
    last_day: dict[int, str] = {}
    once_done: set[int] = set()
    while not stop.is_set():
        try:
            cfg = _load_config()
            now = time.localtime()
            cur = f"{now.tm_hour:02d}:{now.tm_min:02d}"
            day = now.tm_yday
            for s in cfg.get("schedules", []) or []:
                sid = s.get("id")
                if s.get("time") == cur and last_day.get(sid) != day:
                    last_day[sid] = day
                    try:
                        await client.send_text(s.get("jid"), s.get("text") or "")
                        log.debug("sched %s terkirim ke %s", sid, s.get("jid"))
                    except Exception as e:
                        log.warning("sched %s gagal: %s", sid, e)
            # Reminder pribadi: sekali (target/wait_s) & harian (HH:MM).
            for r in cfg.get("reminders", []) or []:
                rid = r.get("id")
                try:
                    if r.get("type") == "once":
                        if rid in once_done:
                            continue
                        ok = False
                        if r.get("wait_s"):
                            ok = (r.get("end_at_t") or 0) <= int(time.time())
                        elif r.get("target"):
                            ok = r.get("target") <= int(time.time())
                        if ok:
                            await client.send_text(r.get("jid"), f"⏰ *Pengingat:* {r.get('text')}")
                            once_done.add(rid)
                    elif r.get("type") == "daily":
                        if r.get("time") == cur:
                            key = rid
                            if last_day.get(key) != day:
                                last_day[key] = day
                                await client.send_text(r.get("jid"), f"⏰ *Pengingat:* {r.get('text')}")
                except Exception as e:
                    log.warning("reminder %s gagal: %s", rid, e)
        except Exception as e:
            log.warning("sched loop err: %s", e)
        try:
            await asyncio.wait_for(stop.wait(), timeout=30)
        except asyncio.TimeoutError:
            pass


# ==================== MAIN ====================

async def _reboot_scheduler(client, stop: asyncio.Event):
    """Dispatch workflow baru sebelum batas ~6 jam; update bio restart."""
    global _EXIT_AFTER_REBOOT
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
            lead_min = max((target + start - time.monotonic()) / 60, 0)
            await _set_bio(client, f"restart in ~{max(lead_min, 0):.0f} min, "
                                   f"will be back in ~{run_min // 60} min")
            ecp = await asyncio.to_thread(_dispatch_run, token)
            if ecp is not None:
                log.info("Dispatch reboot WA berhasil: %s", ecp)
                _EXIT_AFTER_REBOOT = True
                await _set_bio(client, "restart in ~0 min, will be back in "
                                       f"~{run_min // 60} min")
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


class BotRestart(Exception):
    """Dipicu saat bot harus restart in-process (koneksi mati lama, dsb)."""


_EXIT_AFTER_REBOOT = False


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
    last_open = [0.0]
    seen_connected = [False]

    async def _conn_watchdog():
        """Restart in-process kalau koneksi mati >90 detik (anti hang)."""
        while not stop.is_set():
            if seen_connected[0] and last_open[0]:
                idle = time.monotonic() - last_open[0]
                if idle > 90:
                    log.warning("koneksi mati %ds, restart in-process...", int(idle))
                    dead.set()
                    return
            await asyncio.sleep(15)

    async def on_update(update):
        if update.qr:
            print("========== SCAN QR DENGAN WHATSAPP (Settings -> Linked Devices) ==========")
            print(_render_qr(update.qr))
            print("===================== SCAN, LALU KONFIRMASI ==============================")
            _save_qr_svg(update.qr)
        if update.connection:
            log.info("connection=%s is_new_login=%s", update.connection, update.is_new_login)
            if update.connection == "open":
                connected.set()
                last_open[0] = time.monotonic()
                seen_connected[0] = True

    async def on_creds_update(_creds):
        try:
            await auth_state.save_creds()
        except Exception as e:
            log.warning("save creds: %s", e)

    async def _on_msg(data):
        async def _handle():
            try:
                await _on_message(client, data)
            except Exception as e:
                log.exception("handler pesan error: %s", e)
        asyncio.ensure_future(_handle())

    _leave_times: dict[str, int] = {}

    async def _on_stanza_notif(notif):
        try:
            ntype = (notif.attrs or {}).get("type", "")
            if ntype not in ("group-participant-add", "group-participant-remove"):
                return
            from_jid = (notif.attrs or {}).get("from") or ""
            user_jid = (notif.attrs or {}).get("participant") or ""
            if not (_is_group(from_jid) and user_jid):
                return
            cfg = _load_config()
            anti = cfg.setdefault("antimod", {}).get(_jid_key(from_jid), {})
            jtime = int(time.monotonic())
            if ntype == "group-participant-remove":
                reason = ""
                for c in (notif.content or []):
                    if getattr(c, "tag", "") == "remove":
                        reason = (c.attrs or {}).get("reason", "")
                if anti.get("leave") and reason in ("left", "", None):
                    _leave_times[user_jid] = jtime
                    log.info("anti-leave: %s keluar dari %s; dicatat", user_jid, from_jid)
                return
            # group-participant-add
            if anti.get("join"):
                allowed = _allowed(user_jid)
                if not allowed:
                    await _group_participants_update(client, from_jid, "remove", user_jid)
                    log.info("anti-join: %s dikick dari %s (no access)", user_jid, from_jid)
                    return
            if anti.get("leave"):
                # Member yg baru keluar lalu kembali <300 detik -> kick (anti spam keluar-masuk).
                if _leave_times.get(user_jid) and jtime - _leave_times.get(user_jid, 0) < 300:
                    await _group_participants_update(client, from_jid, "remove", user_jid)
                    log.info("anti-leave: %s kembali <5m, dikick dari %s", user_jid, from_jid)
                    _leave_times.pop(user_jid, None)
        except Exception as e:
            log.debug("notif handler err: %s", e)

    client.on("connection.update", on_update)
    client.on("creds.update", on_creds_update)
    client.on("message.decrypted", _on_msg)
    client.on("stanza.notification", _on_stanza_notif)

    await client.connect()

    timeout = int(os.environ.get("WA_QR_TIMEOUT", "0")) or None
    try:
        await asyncio.wait_for(connected.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        log.warning("QR timeout tanpa scan; keluar. Jalankan lagi utk QR baru.")
        await client.disconnect()
        return 0

    me = getattr(getattr(client.socket, "auth", None), "creds", None)
    if me and getattr(me, "me", None) and me.me.id:
        _SELF_JID = me.me.id.split(":")[0].lower()
    log.info("WhatsApp online sebagai %s. Menunggu pesan...", _SELF_JID or "?")

    # Broadcast presence "available" supaya tampil online di kontak.
    try:
        await client.set_presence(True)
        log.info("presence available di-set")
    except Exception as e:
        log.warning("gagal set presence: %s", e)

    # Pastikan config punya owner.
    cfg = _load_config()
    if not cfg.get("owner"):
        cfg["owner"] = _owner()
        _save_config(cfg)
        _save_auth_snapshot()

    # Bio online.
    await _set_bio(client, "online")

    stop = asyncio.Event()
    dead = asyncio.Event()

    async def _sched_wrapper():
        try:
            await _sched_loop(client, stop)
        except asyncio.CancelledError:
            raise
        except BaseException as e:
            log.exception("scheduler crash (%s); lanjut tanpa scheduler...", e)

    async def _reboot_wrapper():
        try:
            await _reboot_scheduler(client, stop)
        except asyncio.CancelledError:
            raise
        except BaseException as e:
            log.exception("reboot scheduler crash (%s); lanjut tanpa reboot...", e)

    _conn_watchdog_task = asyncio.create_task(_conn_watchdog())
    asyncio.create_task(_sched_wrapper())
    asyncio.create_task(_reboot_wrapper())

    idle_wait = asyncio.create_task(asyncio.Event().wait())

    async def _reboot_finished():
        while not _EXIT_AFTER_REBOOT and not stop.is_set():
            await asyncio.sleep(2)

    reboot_wait = asyncio.create_task(_reboot_finished())
    dead_wait = asyncio.create_task(dead.wait())
    try:
        done, _pending = await asyncio.wait(
            {idle_wait, reboot_wait, dead_wait},
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        stop.set()
        idle_wait.cancel()
        reboot_wait.cancel()
        dead_wait.cancel()
        _conn_watchdog_task.cancel()
        await _set_bio(client, "offline")
        await auth_state.save_creds()
        _save_auth_snapshot()
        try:
            await client.disconnect()
        except Exception:
            pass
    return 0 if _EXIT_AFTER_REBOOT else 1


ALLOWED_SET = set(
    x.strip().lower() for x in os.environ.get("WA_ALLOWED", "").split(",") if x.strip()
)

if __name__ == "__main__":
    log = logging.getLogger("wabot")
    _setup_logger()
    while True:
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            rc = loop.run_until_complete(main())
        except KeyboardInterrupt:
            rc = 0
            break
        except BaseException as e:  # crash apapun -> restart in-process
            log.exception("Bot crash (%s); restart dalam 5 detik...", e)
            rc = 1
        else:
            if rc == 0 and _EXIT_AFTER_REBOOT:
                log.info("Run digantikan run baru; keluar bersih.")
                break
            if rc == 0:
                log.info("Bot berhenti (restart); lanjut ke sesi baru...")
        if os.environ.get("WABOT_EXIT_ON_CLEAN") == "1":
            break
        try:
            time.sleep(5)
        except KeyboardInterrupt:
            break
    raise SystemExit(rc)