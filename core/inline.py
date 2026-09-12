"""Tombol inline (opsional) via bot Telegram.

Jika BOT_TOKEN dikonfigurasi, userbot bisa menampilkan menu .help interaktif
dan tombol STOP untuk .gcast/.jgc. Jika tidak, semuanya jatuh ke mode teks biasa.
"""
from telethon import Button, events

from core import config, notify
from core.state import state

HELP = {
    "promo": (
        "📣 PROMO & BROADCAST",
        [
            (".gcast", "Broadcast (reply) ke semua grup"),
            (".gcastt", "Broadcast template promo (acak)"),
            (".gcasts <menit>", "Broadcast terjadwal (reply)"),
            (".addv <teks>", "Tambah template promo"),
            (".delv <idx>", "Hapus template promo"),
            (".listv", "Lihat semua template promo"),
            (".jgc", "Auto-join semua link grup yang terdeteksi"),
            (".stopcast", "Batalkan gcast/jgc yang berjalan"),
        ],
    ),
    "admin": (
        "🛡️ ADMIN & GRUP",
        [
            (".addbl", "Blacklist grup sekarang"),
            (".unbl", "Unblacklist grup sekarang"),
            (".showbl", "Lihat semua grup blacklist"),
            (".ban", "Ban anggota (reply)"),
            (".unban", "Unban anggota (reply)"),
            (".kick", "Kick anggota (reply)"),
            (".promote", "Promote anggota jadi admin (reply)"),
            (".demote", "Demote admin (reply)"),
        ],
    ),
    "automation": (
        "🤖 AUTOMASI",
        [
            (".afk <alasan>", "Mode AFK"),
            (".back", "Nonaktifkan AFK"),
            (".filter add <kata> <balasan>", "Auto-reply kata kunci"),
            (".filter list", "Lihat daftar filter"),
            (".filter del <idx>", "Hapus filter"),
            (".fwd <target>", "Forward pesan dari grup ini ke target"),
            (".fwdlist", "Lihat daftar auto-forward"),
            (".fwdstop", "Hentikan auto-forward grup ini"),
            (".remind <detik> <teks>", "Pengingat"),
        ],
    ),
    "media": (
        "💾 MEDIA",
        [
            (".addqr", "Simpan QR (reply gambar)"),
            (".getqr", "Tampilkan semua QR"),
            (".delqr <idx>", "Hapus QR"),
            (".save", "Forward reply media ke Saved Messages"),
            (".savetoggle", "Auto-save media dari grup ini"),
            (".savelist", "Daftar grup auto-save"),
            (".antidel on/off", "Anti-delete (simpan pesan dihapus)"),
            (".dl <url>", "Download video/audio (yt-dlp)"),
        ],
    ),
    "ai": (
        "✨ AI",
        [
            (".ai <pertanyaan>", "Tanya AI Gemini (reply = konteks)"),
            (".ailist", "Status koneksi AI"),
        ],
    ),
    "info": (
        "📊 INFORMASI",
        [
            (".ping", "Latency bot"),
            (".info", "Info userbot"),
            (".id", "Lihat ID user/grup"),
            (".stats", "Statistik aksi userbot"),
            (".help", "Menu bantuan ini"),
        ],
    ),
}

_bot_username = None


def build_help_text(category=None):
    if category and category in HELP:
        title, items = HELP[category]
        lines = [f"**{title}**", ""]
        for cmd, desc in items:
            lines.append(f"`{cmd}` — {desc}")
        return "\n".join(lines)

    return (
        "**BANTUAN USERBOT**\n\n"
        "Pilih kategori di bawah:\n\n"
        "📣 Promo & Broadcast\n"
        "🛡️ Admin & Grup\n"
        "🤖 Automasi\n"
        "💾 Media\n"
        "✨ AI\n"
        "📊 Informasi\n\n"
        f"Prefix: `{config.PREFIX}`"
    )


def _buttons(category=None):
    if category:
        return [[Button.inline("🔙 Kembali", "help:root")]]
    return [
        [
            Button.inline("📣 Promo", "help:promo"),
            Button.inline("🛡️ Admin", "help:admin"),
        ],
        [
            Button.inline("🤖 Automasi", "help:automation"),
            Button.inline("💾 Media", "help:media"),
        ],
        [
            Button.inline("✨ AI", "help:ai"),
            Button.inline("📊 Info", "help:info"),
        ],
    ]


def attach():
    """Pasang handler inline & callback ke bot client (jika ada)."""
    global _bot_username
    bot = state.bot
    if bot is None:
        return False

    @bot.on(events.InlineQuery)
    async def on_inline(e):
        q = e.text.strip().lower()
        print(f"[INLINE] query diterima: '{q}'")
        if q in ("menu", "help"):
            result = e.builder.article(
                title="Bantuan Userbot",
                text=build_help_text(),
                buttons=_buttons(),
                parse_mode="md",
            )
            await e.answer([result], cache_time=0)
        elif q.startswith("stop:"):
            task = q.split(":", 1)[1] if ":" in q else "gcast"
            result = e.builder.article(
                title="Stop",
                text="Proses berjalan...",
                buttons=[[stop_button(task)]],
                parse_mode="md",
            )
            await e.answer([result], cache_time=0)
        else:
            await e.answer([], cache_time=0)

    @bot.on(events.CallbackQuery)
    async def on_callback(e):
        if not e.data:
            return
        data = e.data.decode(errors="ignore")
        if data.startswith("help:"):
            target = data.split(":", 1)[1]
            if target == "root":
                await e.edit(build_help_text(), buttons=_buttons())
            elif target in HELP:
                await e.edit(build_help_text(target), buttons=_buttons(target))
            else:
                await e.answer("Unknown", alert=True)
        elif data.startswith("stop:"):
            task = data.split(":", 1)[1]
            if task in state.stop:
                state.stop[task] = True
                await e.answer("Stopped", alert=True)
                try:
                    await e.edit("⛔ Proses dihentikan.")
                except Exception:
                    pass
            else:
                await e.answer("Unknown task", alert=True)

    return True


def stop_button(task):
    return Button.inline("⛔ STOP", f"stop:{task}")


async def send_menu(chat_id):
    """Kirim menu bantuan bertombol ke chat. False bila bot tidak tersedia."""
    global _bot_username
    client = state.client
    bot = state.bot
    if client is None or bot is None:
        return False
    try:
        if not _bot_username:
            me = await bot.get_me()
            _bot_username = me.username
        results = await client.inline_query(_bot_username, "menu")
        if not results:
            print("[INLINE] query 'menu' menghasilkan 0 result")
            return False
        await results[0].click(chat_id, hide_via=True)
        return True
    except Exception as e:
        print(f"[INLINE] send_menu gagal: {type(e).__name__}: {e}")
        await notify.log(f"send_menu error: {type(e).__name__}: {e}", "ERROR")
        return False


async def send_stop_panel(chat_id, task):
    """Kirim pesan dengan tombol STOP untuk task (gcast/jgc)."""
    global _bot_username
    client = state.client
    bot = state.bot
    if client is None or bot is None:
        return False
    try:
        if not _bot_username:
            me = await bot.get_me()
            _bot_username = me.username
        results = await client.inline_query(_bot_username, f"stop:{task}")
        if not results:
            return False
        await results[0].click(chat_id, hide_via=True)
        return True
    except Exception as e:
        print(f"[INLINE] send_stop_panel gagal: {type(e).__name__}: {e}")
        return False