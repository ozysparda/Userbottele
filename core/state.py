"""State global bersama antar-module."""
from core.ratelimit import AntiFlood


class State:
    def __init__(self):
        self.client = None
        self.bot = None
        self.owner_id = None
        self.started_at = None
        self.flood = AntiFlood()
        self.stop = {"gcast": False, "jgc": False, "mute": False}
        self.detected_links = set()
        self.ui = None
        self.stats = {"gcast_sent": 0, "auto_reply_sent": 0}


state = State()