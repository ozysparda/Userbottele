"""IG Userbot integration for wabot."""
import os
import time
import json
from pathlib import Path

try:
    import instaloader
    _HAS_INSTALOADER = True
except Exception:
    instaloader = None
    _HAS_INSTALOADER = False

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


class IGNotConfigured(Exception):
    pass


class IGError(Exception):
    pass


class IGClient:
    def __init__(self, whitelist_path: str | Path | None = None):
        self._bot = None
        self._username = None
        self.whitelist_path = Path(whitelist_path) if whitelist_path else None

    def load_whitelist(self) -> list:
        if self.whitelist_path and self.whitelist_path.exists():
            try:
                data = json.loads(self.whitelist_path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return list(data)
            except Exception:
                pass
        return []

    def save_whitelist(self, wl: list):
        if self.whitelist_path:
            self.whitelist_path.parent.mkdir(parents=True, exist_ok=True)
            self.whitelist_path.write_text(json.dumps(wl, indent=2), encoding="utf-8")

    @property
    def available(self) -> bool:
        return _HAS_INSTALOADER

    def login(self, username: str, session_id: str | None = None, session_file: str | None = None):
        if not _HAS_INSTALOADER:
            raise IGError("instaloader belum terpasang di runner ini.")
        username = (username or "").strip().lower().lstrip("@")
        if not username:
            raise IGError("Username IG tidak valid.")
        bot = instaloader.Instaloader()
        bot.context.user_agent = BROWSER_UA
        try:
            if session_file and os.path.exists(session_file):
                bot.load_session_from_file(username, session_file)
            elif session_id:
                bot.context._session.cookies.set("sessionid", str(session_id).strip(), domain=".instagram.com")
                bot.context._session.cookies.set("csrftoken", "instagram", domain=".instagram.com")
                bot.context._session.headers.update({"User-Agent": BROWSER_UA})
                # get_profile dipanggil caller utk memverifikasi session.
            else:
                raise IGError("Butuh sessionid atau path session file.")
        except IGError:
            raise
        except Exception as e:
            raise IGError(f"Gagal set session: {e}")
        self._bot = bot
        self._username = username
        return bot

    def _profile(self):
        if not self._bot or not self._username:
            raise IGNotConfigured("IG belum di-set. Gunakan `.igset <user> <sessionid>`.")
        return self._retry(lambda: instaloader.Profile.from_username(self._bot.context, self._username))

    def _retry(self, fn, wait=300, tries=5):
        last = None
        for i in range(tries):
            try:
                return fn()
            except Exception as e:
                last = e
                time.sleep(wait if i < tries - 1 else 1)
        raise IGError(f"IG gagal setelah retry: {last}")

    def counts(self):
        profile = self._profile()
        followers = self._retry(lambda: {f.username for f in profile.get_followers()}, wait=120)
        following = self._retry(lambda: {f.username for f in profile.get_followees()}, wait=120)
        not_following = sorted(following - followers)
        wl = set(self.load_whitelist())
        return {
            "username": self._username,
            "followers": len(followers),
            "following": len(following),
            "not_following": not_following,
            "safe_count": len([u for u in not_following if u not in wl]),
            "whitelist": sorted(wl),
        }

    def unfollow(self, usernames: list, progress=None):
        if not self._bot:
            raise IGNotConfigured("IG belum di-set.")
        done = 0
        ok = 0
        for u in usernames:
            try:
                self._bot.context.username_unfollow(u)
                ok += 1
            except Exception as e:
                if progress:
                    progress(f"✗ `{u}` gagal: {str(e)[:120]}")
            done += 1
            if progress:
                progress(f"[{done}/{len(usernames)}] `{u}` ✓")
            time.sleep(5)
        return ok