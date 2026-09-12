"""Anti-flood / rate limiter.

3 lapis proteksi biar akun tidak kena FLOOD_WAIT / limiter oleh Telegram:
1. Proactive rate limit per-kategori (sliding window) + per-peer interval.
2. Adaptive backoff: setiap kena FloodWait, kelipatan delay naik (x2, maks 64).
3. Global gap + jitter biar pola kirim terlihat alami (tidak seragam).
"""
import asyncio
import random
import time

from core import config


class AntiFlood:
    def __init__(self):
        self._counts = {}
        self._peer_last = {}
        self._factor = 1.0
        self._last_flood = 0.0
        self._decay_task = None

    # ---------- internal ----------
    def _recent(self, category, window):
        now = time.monotonic()
        dq = self._counts.setdefault(category, [])
        while dq and now - dq[0] > window:
            dq.pop(0)
        return dq

    # ---------- public ----------
    async def wait(self, category, rate, window=60, peer=None, peer_interval=0.0):
        """Tunggu hingga slot tersedia untuk aksi pada kategori entu."""
        dq = self._recent(category, window)
        if len(dq) >= rate:
            wait = window - (time.monotonic() - dq[0])
            if wait > 0:
                await asyncio.sleep(wait * self._factor)

        if peer is not None and peer_interval > 0:
            key = (category, peer)
            last = self._peer_last.get(key, 0.0)
            gap = peer_interval - (time.monotonic() - last)
            if gap > 0:
                await asyncio.sleep(gap * self._factor)

        self._counts.setdefault(category, []).append(time.monotonic())
        if peer is not None:
            self._peer_last[(category, peer)] = time.monotonic()

        gap = (config.GLOBAL_GAP + random.uniform(0, config.JITTER_MAX)) * self._factor
        if gap > 0:
            await asyncio.sleep(gap)

    async def on_flood(self, seconds):
        """Setelah exception FloodWaitError. Naikkan backoff & tidur."""
        self._factor = min(64.0, self._factor * 2)
        self._last_flood = time.monotonic()
        wait = max(float(seconds), 2.0) * self._factor
        await asyncio.sleep(wait)

    async def _decay(self):
        while True:
            await asyncio.sleep(600)
            if time.monotonic() - self._last_flood > 3600:
                self._factor = max(1.0, self._factor / 2)

    def start(self):
        if self._decay_task is None:
            self._decay_task = asyncio.ensure_future(self._decay())

    @property
    def factor(self):
        return self._factor