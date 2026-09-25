"""Penyimpanan JSON yang aman (atomic write) untuk data userbot."""
import json
import os
import sys
import threading
from pathlib import Path

if getattr(sys, "frozen", False):
    DATA_DIR = Path(sys.executable).resolve().parent / "data"
else:
    DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

_lock = threading.Lock()


def _path(name):
    if not name.endswith(".json"):
        name += ".json"
    return DATA_DIR / name


def load(name, default):
    p = _path(name)
    if not p.exists():
        return default
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def save(name, data):
    with _lock:
        p = _path(name)
        tmp = p.with_suffix(".json.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, p)
        except OSError:
            pass


def update(name, default, mutator):
    """Load data, mutasi lewat callable, simpan kembali. Return hasil."""
    data = load(name, default)
    data = mutator(data)
    save(name, data)
    return data