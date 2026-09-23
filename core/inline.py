"""Tombol inline (opsional) via bot Telegram.

Jika BOT_TOKEN dikonfigurasi, userbot bisa menampilkan menu .help interaktif
dan tombol STOP untuk .gcast/.jgc. Jika tidak, semuanya jatuh ke mode teks biasa.
"""
from telethon import Button, events

from core import config, notify
from core.state import state

HELP = {
    "gcast": (
        "📣 BROADCAST GLOBAL",
        [
            (".gcast <pesan>", "Broadcast ke semua grup (reply atau teks langsung)"),
            (".gcastt", "Broadcast template (acak)"),
            (".gcasts <menit>", "Broadcast terjadwal (reply)"),
            (".addv <teks>", "Tambah template"),
            (".delv <idx>", "Hapus template"),
            (".listv", "Lihat semua template"),
            (".gcastpm <pesan>", "Broadcast ke semua PM/inbox (reply atau teks)"),
            (".gcron 09:30 <pesan>", "Broadcast berulang tiap hari (list/del)"),
            (".jgc", "Auto-join semua link grup yang terdeteksi"),
            (".joinadd <link>", "Simpan link grup (t.me/+ atau joinchat)"),
            (".joinlist", "Lihat link tersimpan"),
            (".joindel <idx>", "Hapus link tersimpan"),
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
            (".toimg", "Reply stiker -> jadi foto (JPG)"),
            (".sticker / .stk", "Reply pesan -> kartu stiker (foto+nama+text)"),
        ],
    ),
    "access": (
        "🔓 AKSES",
        [
            (".giveaccess <id|@username> <menit> (atau .ga, reply juga bisa)", "Beri akses command sementara"),
            (".revokeaccess <id> (atau .ra)", "Cabut akses"),
            (".accesslist", "Daftar akses aktif + sisa waktu"),
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
    "tools": (
        "🛠️ UTILITAS",
        [
            (".calc <ekspresi>", "Kalkulator (contoh: .calc sqrt(144) + 5)"),
            (".del", "Hapus pesan (reply). Tanpa reply = hapus sendiri"),
            (".tr id <teks>", "Translate ke bahasa lain (reply juga bisa)"),
        ],
    ),
    "gc": (
        "👥 JOIN GRUP",
        [
            (".joingc [n] [jeda]", "Join n grup via invite link (default 20, cooldown 60s)"),
            (".stopjgc", "Hentikan proses join GC"),
            (".gclink <link...>", "Simpan invite link ke daftar"),
            (".gclist", "Lihat status link & statistik join"),
            (".gcflush", "Hapus semua data join & link"),
        ],
    ),
    "mute": (
        "🔇 NOTIFIKASI",
        [
            (".muteall [jeda]", "Mute notifikasi semua chat"),
            (".unmuteall [jeda]", "Unmute semua chat"),
            (".mutegc [jeda]", "Mute semua grup/channel (GC)"),
            (".unmutegc [jeda]", "Unmute semua grup/channel (GC)"),
            (".mutepm [jeda]", "Mute semua chat pribadi (PM)"),
            (".unmutepm [jeda]", "Unmute semua chat pribadi (PM)"),
            (".mutechat [jam] / .mute", "Mute chat ini (default selamanya)"),
            (".unmutechat / .unmute", "Unmute chat ini"),
            (".stopmute", "Hentikan proses mute/unmute"),
            (".muteflush", "Reset memori mute (semua diproses lagi)"),
            (".mutestat", "Statistik chat yang di-mute"),
        ],
    ),
    "vc": (
        "🎙️ VOICE CHAT",
        [
            (".vcstart [chat|@username]", "Akun selalu berdiam di VC target (auto-buat & auto-rejoin)"),
            (".vcstop", "Keluar dari VC & hapus target"),
            (".vcstat", "Status voice chat"),
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
        "📣 Broadcast Global\n"
        "🛡️ Admin & Grup\n"
        "🤖 Automasi\n"
        "💾 Media\n"
        "✨ AI\n"
        "🛠️ Utilitas\n"
        "👥 Join Grup\n"
        "🔇 Notifikasi\n"
        "🎙️ Voice Chat\n"
        "🔓 Akses\n"
        "📊 Informasi\n\n"
        f"Prefix: `{config.PREFIX}`"
    )


def _buttons(category=None):
    if category:
        return [[Button.inline("🔙 Kembali", "help:root")]]
    return [
        [
            Button.inline("📣 Gcast", "help:gcast"),
            Button.inline("🛡️ Admin", "help:admin"),
        ],
        [
            Button.inline("🤖 Automasi", "help:automation"),
            Button.inline("💾 Media", "help:media"),
        ],
        [
            Button.inline("✨ AI", "help:ai"),
            Button.inline("🛠️ Utilitas", "help:tools"),
        ],
        [
            Button.inline("👥 Join Grup", "help:gc"),
            Button.inline("🔇 Notifikasi", "help:mute"),
        ],
        [
            Button.inline("🎙️ Voice Chat", "help:vc"),
            Button.inline("🔓 Akses", "help:access"),
        ],
        [
            Button.inline("📊 Info", "help:info"),
        ],
    ]


async def _on_callback(e):
    owner_id = state.owner_id
    if owner_id and e.query.user_id != owner_id:
        await e.answer("⛔ Hanya owner yang bisa.", alert=True)
        return
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


def attach():
    """Pasang handler callback ke client user + bot (jika ada)."""
    client = state.client

    @client.on(events.CallbackQuery)
    async def _cb_user(e):
        await _on_callback(e)

    bot = state.bot
    if bot is not None:
        @bot.on(events.CallbackQuery)
        async def _cb_bot(e):
            await _on_callback(e)

        @bot.on(events.InlineQuery)
        async def on_inline(e):
            if state.owner_id and e.query.user_id != state.owner_id:
                await e.answer([], cache_time=0)
                return
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

    return True


def stop_button(task):
    return Button.inline("⛔ STOP", f"stop:{task}")


async def send_menu(chat_id):
    """Kirim bantuan bertombol. Prioritas: via bot inline (ada 'via @bot'),
    fallback kirim langsung dari akun user biar tombol selalu muncul."""
    client = state.client
    bot = state.bot
    if client is None:
        return False
    if bot is not None:
        try:
            global _bot_username
            if not _bot_username:
                me = await bot.get_me()
                _bot_username = me.username
            results = await client.inline_query(_bot_username, "menu")
            if results:
                await results[0].click(chat_id, hide_via=False)
                return True
        except Exception as e:
            print(f"[INLINE] send_menu via bot gagal: {type(e).__name__}: {e}")
    try:
        await client.send_message(chat_id, build_help_text(), buttons=_buttons(), parse_mode="md")
        return True
    except Exception as e:
        print(f"[INLINE] send_menu gagal: {type(e).__name__}: {e}")
        await notify.log(f"send_menu error: {type(e).__name__}: {e}", "ERROR")
        return False


async def send_stop_panel(chat_id, task):
    """Kirim panel STOP via bot inline dulu, fallback langsung dari akun user."""
    client = state.client
    bot = state.bot
    if client is None:
        return False
    if bot is not None:
        try:
            global _bot_username
            if not _bot_username:
                me = await bot.get_me()
                _bot_username = me.username
            results = await client.inline_query(_bot_username, f"stop:{task}")
            if results:
                await results[0].click(chat_id, hide_via=False)
                return True
        except Exception as e:
            print(f"[INLINE] send_stop_panel via bot gagal: {type(e).__name__}: {e}")
    try:
        await client.send_message(
            chat_id,
            f"⚙️ Proses **{task}** sedang berjalan...",
            buttons=[[stop_button(task)]],
        )
        return True
    except Exception as e:
        print(f"[INLINE] send_stop_panel gagal: {type(e).__name__}: {e}")
        return False