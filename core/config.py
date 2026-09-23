"""Konfigurasi userbot. Membaca dari file .env (jika ada) + environment variables."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

VERSION = "2.1.0"


def _load_dotenv():
    path = BASE_DIR / ".env"
    if not path.exists():
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


_load_dotenv()


def get(key, default=None):
    return os.environ.get(key, default)


def get_int(key, default):
    try:
        return int(get(key, default))
    except (TypeError, ValueError):
        return default


def get_float(key, default):
    try:
        return float(get(key, default))
    except (TypeError, ValueError):
        return default


def get_bool(key, default=False):
    v = get(key)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def get_list(key):
    v = get(key)
    if not v:
        return []
    return [x.strip() for x in v.split("|") if x.strip()]


# ===== AKUN =====
API_ID = get_int("API_ID", 0)
API_HASH = get("API_HASH", "")
BOT_TOKEN = get("BOT_TOKEN", "")
STRING_SESSION = get("STRING_SESSION", "")
OWNER_ID = get_int("OWNER_ID", 0)

# ===== LOG =====
LOG_CHAT_ID = get_int("LOG_CHAT_ID", 0)

# ===== AI =====
GEMINI_KEY = get("GEMINI_KEY", "")
GEMINI_MODEL = get("GEMINI_MODEL", "gemini-3.6-flash")
# Provider AI: opencode | gemini | auto (auto = pakai opencode bila terpasang)
AI_PROVIDER = get("AI_PROVIDER", "auto")
# Model untuk opencode, misal google/gemini-3.6-flash atau opencode/big-pickle
OPENCODE_MODEL = get("OPENCODE_MODEL", "")
# Isi JSON file auth opencode (untuk provider yang butuh login, misal opencode/big-pickle)
OPENCODE_AUTH_JSON = get("OPENCODE_AUTH_JSON", "")

# ===== ANTI-BAN / RATE LIMIT =====
SEND_RATE = get_int("SEND_RATE", 30)
SEND_WINDOW = get_int("SEND_WINDOW", 60)
GROUP_SEND_INTERVAL = get_float("GROUP_SEND_INTERVAL", 3.0)
GLOBAL_GAP = get_float("GLOBAL_GAP", 0.5)
JITTER_MAX = get_float("JITTER_MAX", 1.5)
JOIN_LIMIT = get_int("JOIN_LIMIT", 10)
JOIN_WINDOW = get_int("JOIN_WINDOW", 600)
JOIN_DELAY_MIN = get_float("JOIN_DELAY_MIN", 35.0)
JOIN_DELAY_MAX = get_float("JOIN_DELAY_MAX", 60.0)

# ===== BROADCAST / TEMPLATE =====
VARIANTS = get_list("VARIANTS")

# ===== LAIN-LAIN =====
PREFIX = get("PREFIX", ".")
WATERMARK_TEXT = get("WATERMARK_TEXT", "")
MASTER_PASS = get("MASTER_PASS", "")