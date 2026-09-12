"""Utilities umum: owner check, watermark, progres, parsial command."""
import re

from telethon.tl.types import Channel, Chat, User

from core import config, state

PREFIX = config.PREFIX
ESCAPED_PREFIX = re.escape(PREFIX)


def cmd(names, extra=""):
    """Buat regex pattern untuk command userbot.

    names: str atau list str. extra: bagian pattern opsional setelah nama command.
    """
    if isinstance(names, str):
        names = [names]
    joined = "|".join(re.escape(n) for n in names)
    return rf"^{ESCAPED_PREFIX}(?:{joined})\b{extra}"


def wm(text):
    """Tambahkan watermark ke teks (kalau dikonfigurasi)."""
    if config.WATERMARK_TEXT:
        return f"{text}\n\n{config.WATERMARK_TEXT}"
    return text


def strip_wm(text):
    """Hapus pesan yang mencurigakan request mast-head."""
    if config.WATERMARK_TEXT and text.endswith(config.WATERMARK_TEXT):
        return text[: -len(config.WATERMARK_TEXT)].rstrip("\n")
    return text


async def owner_id():
    if not state.owner_id and state.client:
        me = await state.client.get_me()
        state.owner_id = me.id
    return state.owner_id


def is_owner(uid):
    if state.owner_id and uid == state.owner_id:
        return True
    return False


def progress_bar(cur, total, size=12):
    if total <= 0:
        return "[================]"
    filled = int(round(cur / total * size))
    return "[" + "\u2588" * filled + "\u2591" * (size - filled) + "]"


def parse_args(args_text):
    return [a for a in args_text.split() if a]


async def get_entity_id(client, text):
    """Resolve username/ID ke entity (untuk .id / admin tools)."""
    text = text.strip().lstrip("@")
    try:
        return await client.get_input_entity(text)
    except Exception:
        return None


def is_group(entity):
    return isinstance(entity, (Chat, Channel))


def is_user(entity):
    return isinstance(entity, User)


def chat_title(entity):
    try:
        return getattr(entity, "title", None) or getattr(entity, "username", None) or "?"
    except Exception:
        return "?"