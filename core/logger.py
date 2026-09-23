"""Logger detail: rekam semua input/userbot ke ring buffer JSON persisten.

Setiap event (pesan masuk/keluar, command, notifikasi) dicatat dengan
timestamp + level + isi + detail. Bisa dilihat lewat .log di Telegram.
"""
import time

from core import store

KEY = "log_entries"
MAX_LOG = 400


def record(level, text, detail=None):
    entries = store.load(KEY, [])
    entries.append(
        {
            "t": int(time.time()),
            "level": level,
            "text": text,
            "detail": detail,
        }
    )
    if len(entries) > MAX_LOG:
        entries = entries[-MAX_LOG:]
    store.save(KEY, entries)


def recent(n=20, level=None):
    entries = store.load(KEY, [])
    if level:
        entries = [e for e in entries if e["level"] == level]
    return entries[-n:]


def stats():
    entries = store.load(KEY, [])
    counts = {}
    for e in entries:
        counts[e.get("level", "?")] = counts.get(e.get("level", "?"), 0) + 1
    return {"total": len(entries), "counts": counts}


def clear():
    store.save(KEY, [])