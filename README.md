# Userbottele v2

Userbot Telegram (Python + Telethon) untuk broadcast global, auto-join grup, automasi, media, dan AI — dilengkapi perlindungan anti-flood supaya akun aman dari limiter Telegram.

## ⚠️ Perhatian (wajib baca)

- **Jangan pernah commit file `.env`, `*.session`, atau folder `data/`** — itu kredensial & data login akun.
- Repo lama sempat meng-*commit* `userbot.session` + api_id/api_hash. Sudah di-untrack, tapi kalau repo kamu public sebaiknya **revoke session** dan ganti api keys: settings > privacy & security > active sessions.

## Fitur

### 📣 Broadcast Global
| Command | Fungsi |
|---|---|
| `.gcast <pesan>` | Broadcast ke semua grup — reply pesan **atau** ketik teks langsung (progress + tombol STOP) |
| `.gcastt` | Broadcast template (dipilih acak dari `.addv`) |
| `.gcasts <menit>` | Broadcast terjadwal |
| `.addv <teks>` / `.delv <idx>` / `.listv` | Kelola template |
| `.jgc` | Auto-join semua link grup `t.me/+...` yang terdeteksi |
| `.joinadd <link>` / `.joinlist` / `.joindel <idx>` | Simpan & kelola daftar link join custom |
| `.gcastpm <pesan>` | Broadcast ke semua PM/inbox |
| `.gcron 09:30 <pesan>` | Broadcast berulang tiap hari (`list` / `del <idx>`) |
| `.stopcast` | Batalkan gcast/jgc |

### 🛡️ Admin & Grup
`.addbl` `.unbl` `.showbl` `.ban` `.unban` `.kick` `.promote` `.demote`

### 🤖 Automasi
`.afk` `.back` `.filter add/list/del` `.fwd` `.fwdlist` `.fwdstop` `.remind`

### 💾 Media
`.addqr` `.getqr` `.delqr` `.save` `.savetoggle` `.savelist` `.antidel on/off` `.dl <url>` `.dla <url>`

### ✨ AI (opsional, set `GEMINI_KEY`)
`.ai <pertanyaan>` `.ailist`

### 📊 Informasi
`.ping` `.info` `.id` `.stats` `.help`

## Instalasi (Termux / PC / VPS)

1. Clone repo:
   ```bash
   git clone https://github.com/ozysparda/Userbottele.git
   cd Userbottele
   ```
2. Install dependency:
   ```bash
   pip install -r requirements.txt
   ```
3. Buat file `.env` dari contoh:
   ```bash
   cp .env.example .env
   nano .env        # isi API_ID & API_HASH (https://my.telegram.org)
   ```
   Catatan: `.env` sudah berisi api lama userbot ini. **Ganti/amankan** kalau perlu.
4. Jalankan:
   ```bash
   python UserBot.py
   ```
   Masukkan nomor HP (+62...) dan kode OTP saat diminta. Session tersimpan lokal sebagai `userbot.session` — tidak ikut ter-commit.

Cek konfigurasi tanpa login:
```bash
python UserBot.py --check
```

## Fitur opsional (lewat `.env`)

- **Tombol inline UI** — set `BOT_TOKEN` (buat bot di @BotFather, aktifkan inline mode). Menu `.help` jadi interaktif + tombol STOP di gcast/jgc.
- **AI Gemini** — set `GEMINI_KEY` (https://aistudio.google.com/apikey). Bisa pakai model lain via `GEMINI_MODEL`.
- **StringSession** — set `STRING_SESSION` kalau mau pindah-pindah device / host cloud (generate via string session generator Telethon).
- **Template** — set `VARIANTS=teks1|teks2|...` atau pakai `.addv`.
- **Logging** — set `LOG_CHAT_ID` kalau mau log aksi dikumpulkan ke grup khusus.

## Anti-ban / rate limit

Bisa diatur di `.env`:
- `SEND_RATE` / `SEND_WINDOW` — kecepatan kirim global.
- `GROUP_SEND_INTERVAL` — jeda minimal antar grup pada gcast.
- `JOIN_LIMIT` / `JOIN_WINDOW` / `JOIN_DELAY_MIN` / `JOIN_DELAY_MAX` — untuk `.jgc`.
- `GLOBAL_GAP` / `JITTER_MAX` — jeda acak biar pola kirim tidak seperti bot.

> Userbot ini untuk keperluan yang sah dan patut. Penggunaan berlebihan melanggar ToS Telegram dan berisiko ban. Gunakan dengan bijak.