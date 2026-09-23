"""Logging ringan ke Saved Messages atau LOG_CHAT_ID. Juga dicatat ke logger detail."""
from core import config, logger
from core.state import state


async def log(text, level="INFO"):
    try:
        logger.record(level, text)
    except Exception:
        pass
    if not state.client:
        return
    try:
        peer = config.LOG_CHAT_ID if config.LOG_CHAT_ID else "me"
        await state.client.send_message(peer, f"[{level}] {text}")
    except Exception:
        pass


async def log_error(text):
    await log(text, "ERROR")