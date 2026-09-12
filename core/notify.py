"""Logging ringan ke Saved Messages atau LOG_CHAT_ID."""
from core import config
from core.state import state


async def log(text, level="INFO"):
    if not state.client:
        return
    try:
        peer = config.LOG_CHAT_ID if config.LOG_CHAT_ID else "me"
        await state.client.send_message(peer, f"[{level}] {text}")
    except Exception:
        pass


async def log_error(text):
    await log(text, "ERROR")