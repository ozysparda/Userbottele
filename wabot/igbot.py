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

    def login(self, username: str, session_id: str | None = None, session_file: str | None = None, cookies: dict | None = None):
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
            else:
                cj = bot.context._session.cookies
                if cookies:
                    for k, v in cookies.items():
                        if v:
                            cj.set(str(k), str(v), domain=".instagram.com")
                if not session_id:
                    raise IGError("Lupa kirim sessionid.")
                if session_id:
                    cj.set("sessionid", str(session_id).strip(), domain=".instagram.com")
                if "csrftoken" not in cj:
                    cj.set("csrftoken", "instagram", domain=".instagram.com")
                if "ig_did" not in cj:
                    import uuid
                    cj.set("ig_did", str(uuid.uuid4()), domain=".instagram.com")
                bot.context._session.headers.update({"User-Agent": BROWSER_UA})
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

    def followers(self, progress=None) -> set:
        if progress:
            progress("📥 Muat daftar followers…")
        profile = self._profile()
        return self._retry(lambda: {f.username for f in profile.get_followers()}, wait=120)

    def counts(self, progress=None):
        if progress:
            progress("🔑 Ambil profil…")
        profile = self._profile()
        followers = self.followers(progress)
        if progress:
            progress("📤 Muat daftar following…")
        following = self._retry(lambda: {f.username for f in profile.get_followees()}, wait=120)
        if progress:
            progress("🧮 Hitung selisih & whitelist…")
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

    def checkpoint(self, ck_path: str | Path, progress=None) -> dict:
        ck_path = Path(ck_path)
        ck_path.parent.mkdir(parents=True, exist_ok=True)
        users = sorted(self.followers(progress))
        if progress:
            progress("💾 Tulis checkpoint…")
        data = {"username": self._username, "ts": int(time.time()), "followers": users}
        ck_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return data

    def unfollowed_since(self, ck_path: str | Path, progress=None) -> dict:
        ck_path = Path(ck_path)
        if not ck_path.exists():
            return {}
        try:
            data = json.loads(ck_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        ck_followers = set(data.get("followers") or [])
        now = self.followers(progress)
        if progress:
            progress("🧮 Bandingkan dgn checkpoint…")
        gone = sorted(ck_followers - now)
        return {
            "username": self._username,
            "checkpoint_ts": int(data.get("ts") or 0),
            "checkpoint_username": data.get("username"),
            "current": len(now),
            "at_checkpoint": len(ck_followers),
            "unfollowed": gone,
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