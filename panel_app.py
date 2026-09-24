"""Panel kontrol desktop (Windows) untuk Userbottele.

Jalankan:  python UserBot.py --panel    atau   python panel_app.py
Build exe:  powershell .\\build_exe.ps1   (membutuhkan PyInstaller)

Fitur:
- Dashboard tombol: Start / Stop / Simpan Config / Login Akun
- Tab Config (.env), Akun (login OTP), dan Log live
"""
import asyncio
import subprocess
import sys
import threading
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import messagebox, scrolledtext, ttk
except ImportError:
    print("Tkinter tidak tersedia. Install Python dari python.org (bukan Windows Store).")
    sys.exit(1)

def _base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


BASE_DIR = _base_dir()
ENV_PATH = BASE_DIR / ".env"

FIELDS = [
    ("API_ID", "akun"),
    ("API_HASH", "akun"),
    ("STRING_SESSION", "akun"),
    ("BOT_TOKEN", "akun"),
    ("OWNER_ID", "akun"),
    ("GEMINI_KEY", "ai"),
    ("GEMINI_MODEL", "ai"),
    ("GEMINI_IMG_MODEL", "ai"),
    ("AI_PROVIDER", "ai"),
    ("OPENCODE_MODEL", "ai"),
    ("PREFIX", "lain"),
    ("LOG_CHAT_ID", "lain"),
    ("WATERMARK_TEXT", "lain"),
]

SECTIONS = {
    "akun": "AKUN & STRING SESSION",
    "ai": "AI",
    "lain": "LAIN-LAIN",
}

SENSI = {"STRING_SESSION", "API_HASH", "BOT_TOKEN", "GEMINI_KEY"}

# ==== Palet warna (Windows 10/11) ====
BG = "#0f172a"
BG2 = "#1e2a3a"
CARD = "#263449"
TEXT = "#e2e8f0"
MUTED = "#94a3b8"
GREEN = "#22c55e"
RED = "#ef4444"
BLUE = "#3b82f6"
AMBER = "#f59e0b"
BORDER = "#334155"


def _load_env():
    data = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            data[k.strip()] = v.strip()
    return data


def _save_env(data):
    lines = []
    for key, group in FIELDS:
        val = data.get(key, "")
        lines.append(f"{key}={val}")
    for k, v in data.items():
        if k not in {x for x, _ in FIELDS} and "=" not in k and k:
            lines.append(f"{k}={v}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


class PanelApp:
    def __init__(self, root):
        self.root = root
        self.proc = None
        self.entries = {}
        # Dedicated event loop thread untuk telethon (async API)
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, daemon=True).start()
        self._setup_style()
        self._build()
        self._load_to_form()
        self._refresh_status()

    def _run(self, coro, timeout=60):
        # jalankan coroutine di loop thread panel, blocking sampai selesai
        fut = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result(timeout)

    # ---------- Style & Layout ----------
    def _setup_style(self):
        self.root.title("Userbottele Panel")
        self.root.geometry("920x640")
        self.root.configure(bg=BG)
        self.root.minsize(760, 520)
        try:
            self.root.iconbitmap(default="")
        except Exception:
            pass
        st = ttk.Style()
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure(".", background=BG, foreground=TEXT, font=("Segoe UI", 10))
        st.configure("TFrame", background=BG)
        st.configure("Card.TFrame", background=CARD)
        st.configure("TLabel", background=BG, foreground=TEXT)
        st.configure("Card.TLabel", background=CARD, foreground=TEXT)
        st.configure("Muted.TLabel", background=BG, foreground=MUTED)
        st.configure("Header.TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 16, "bold"))
        st.configure("SubHeader.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 9))
        st.configure(
            "TButton", background=BLUE, foreground="white",
            borderwidth=0, focusthickness=0, padding=8, font=("Segoe UI", 10, "bold"))
        st.map("TButton", background=[("active", "#2563eb"), ("disabled", "#334155")])
        st.configure("Danger.TButton", background=RED)
        st.map("Danger.TButton", background=[("active", "#dc2626"), ("disabled", "#334155")])
        st.configure("Success.TButton", background=GREEN)
        st.map("Success.TButton", background=[("active", "#16a34a"), ("disabled", "#334155")])
        st.configure("Ghost.TButton", background=CARD)
        st.map("Ghost.TButton", background=[("active", "#31415a"), ("disabled", "#263449")])
        st.configure(
            "TEntry", fieldbackground="#0b1526", foreground=TEXT,
            insertcolor=TEXT, bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)
        st.configure(
            "TNotebook", background=BG, borderwidth=0, tabmargins=(8, 8, 8, 0))
        st.configure(
            "TNotebook.Tab", background=BG2, foreground=MUTED, padding=(14, 8))
        st.map("TNotebook.Tab", background=[("selected", CARD)], foreground=[("selected", "white")])
        st.configure("TProgressbar", background=GREEN, troughcolor=BG2, borderwidth=0)

    def _build(self):
        container = tk.Frame(self.root, bg=BG)
        container.pack(fill="both", expand=True)

        # ===== Header =====
        header = tk.Frame(container, bg=BG, pady=12)
        header.pack(fill="x", padx=16)
        hleft = tk.Frame(header, bg=BG)
        hleft.pack(side="left")
        tk.Label(hleft, text="🤖 Userbottele", font=("Segoe UI", 17, "bold"),
                 bg=BG, fg=TEXT).pack(anchor="w")
        tk.Label(hleft, text="Panel kontrol userbot", font=("Segoe UI", 9),
                 bg=BG, fg=MUTED).pack(anchor="w")

        self.btn_start = self._big_button(header, "▶  Start", GREEN, self._start, side="left")
        self.btn_stop = self._big_button(header, "⏹  Stop", RED, self._stop, side="left")
        self._big_button(header, "💾  Simpan Config", BLUE, self._save_form, side="left")
        self._big_button(header, "🔑  Login Akun", AMBER, self._go_akun, side="left", ghost=True)

        # Status badge
        self.status_var = tk.StringVar()
        self.status_dot = tk.Canvas(header, width=14, height=14, bg=BG, highlightthickness=0)
        self.status_dot.pack(side="right", padx=(8, 4))
        tk.Label(header, textvariable=self.status_var, font=("Segoe UI", 10, "bold"),
                 bg=BG, fg=TEXT).pack(side="right")

        # ===== Notebook =====
        nb = ttk.Notebook(container)
        self.nb = nb
        nb.pack(fill="both", expand=True, padx=16, pady=(4, 16))
        nb.bind("<<NotebookTabChanged>>", lambda e: self._refresh_status())

        cfg = ttk.Frame(nb, style="Card.TFrame")
        nb.add(cfg, text="  Config  ")
        self._build_config_tab(cfg)

        akun = ttk.Frame(nb, style="Card.TFrame")
        nb.add(akun, text="  Akun  ")
        self._build_akun_tab(akun)

        log = ttk.Frame(nb, style="Card.TFrame")
        nb.add(log, text="  Log  ")
        self._build_log_tab(log)

    def _big_button(self, parent, text, color, cmd, side="top", ghost=False):
        b = tk.Button(
            parent, text=text, command=cmd,
            bg=color if not ghost else CARD, fg="white", activebackground="#31415a",
            activeforeground="white", relief="flat", bd=0, padx=14, pady=8,
            font=("Segoe UI", 10, "bold"), cursor="hand2", highlightthickness=0)
        b.pack(side=side, padx=6)
        return b

    def _refresh_status(self, *_):
        if self.proc and self.proc.poll() is None:
            self.status_var.set("●  Berjalan")
            self._set_dot(GREEN)
        else:
            self.status_var.set("○  Berhenti")
            self._set_dot(MUTED)

    def _set_dot(self, color):
        self.status_dot.delete("all")
        self.status_dot.create_oval(2, 2, 12, 12, fill=color, outline="")

    def _go_akun(self):
        self.nb.select(1)

    # ---------- Config ----------
    def _build_config_tab(self, parent):
        form = ttk.Frame(parent, style="Card.TFrame")
        form.pack(fill="both", expand=True, padx=14, pady=14)

        r = 0
        last_section = None
        for key, group in FIELDS:
            if group != last_section:
                tk.Label(form, text=SECTIONS[group], font=("Segoe UI", 10, "bold"),
                         bg=CARD, fg=BLUE).grid(row=r, column=0, columnspan=2, sticky="w", pady=(12, 4))
                r += 1
                last_section = group
            tk.Label(form, text=f"{key}:", font=("Segoe UI", 9),
                     bg=CARD, fg=TEXT).grid(row=r, column=0, sticky="e", padx=(0, 8), pady=3)
            show = "" if key in SENSI else None
            ent = tk.Entry(form, width=74, bg="#0b1526", fg=TEXT, insertbackground=TEXT,
                           relief="flat", font=("Segoe UI", 9),
                           highlightthickness=1, highlightbackground=BORDER,
                           highlightcolor=BLUE, show=show)
            ent.grid(row=r, column=1, sticky="ew", pady=3, ipady=4)
            self.entries[key] = ent
            r += 1

        form.columnconfigure(1, weight=1)
        btns = ttk.Frame(form, style="Card.TFrame")
        btns.grid(row=r, column=0, columnspan=2, sticky="w", pady=(14, 0))
        ttk.Button(btns, text="💾 Simpan", command=self._save_form).pack(side="left")
        ttk.Button(btns, text="📂 Muat .env", command=self._load_to_form, style="Ghost.TButton").pack(side="left", padx=6)
        ttk.Button(btns, text="👁 Toggle", command=self._toggle_secret, style="Ghost.TButton").pack(side="left")

    def _toggle_secret(self):
        for key, ent in self.entries.items():
            if key in SENSI:
                ent.config(show="" if ent.cget("show") else "*")

    def _load_to_form(self):
        data = _load_env()
        for key, ent in self.entries.items():
            ent.delete(0, "end")
            ent.insert(0, data.get(key, ""))

    def _save_form(self):
        data = {}
        for key, ent in self.entries.items():
            data[key] = ent.get().strip()
        data = {**_load_env(), **data}
        _save_env(data)
        messagebox.showinfo("Tersimpan", f"Config disimpan ke .env\n({ENV_PATH})")

    # ---------- Akun / Login ----------
    def _build_akun_tab(self, parent):
        self._akun_phone = None
        self._akun_client = None
        self._akun_qr = None
        pad = ttk.Frame(parent, style="Card.TFrame", padding=14)
        pad.pack(fill="both", expand=True)

        tk.Label(pad, text="Login akun Telegram untuk userbot", font=("Segoe UI", 13, "bold"),
                 bg=CARD, fg=TEXT).pack(anchor="w")
        tk.Label(pad, text="Session (cookie) otomatis disimpan ke .env setelah berhasil.",
                 font=("Segoe UI", 9), bg=CARD, fg=MUTED).pack(anchor="w", pady=(0, 10))

        tk.Label(pad, text="Nomor HP (mis. +62xxx):", bg=CARD, fg=TEXT).pack(anchor="w")
        self.akun_phone_entry = self._entry(pad)
        self.akun_phone_entry.pack(fill="x", pady=4)

        self.btn_send_code = ttk.Button(pad, text="📨  Kirim Kode", command=self._akun_send_code)
        self.btn_send_code.pack(anchor="w", pady=(4, 10))

        tk.Label(pad, text="Kode OTP (dikirim Telegram):", bg=CARD, fg=TEXT).pack(anchor="w")
        self.akun_code_entry = self._entry(pad)
        self.akun_code_entry.pack(fill="x", pady=4)

        tk.Label(pad, text="Password 2FA (isi jika akun pakai 2FA):", bg=CARD, fg=TEXT).pack(anchor="w")
        self.akun_pass_entry = self._entry(pad, secret=True)
        self.akun_pass_entry.pack(fill="x", pady=4)

        self.btn_login = ttk.Button(pad, text="🔑  Login & Simpan Session",
                                    command=self._akun_login, state="disabled")
        self.btn_login.pack(anchor="w", pady=(8, 6))

        self.akun_status = tk.StringVar(value="Belum login.")
        tk.Label(pad, textvariable=self.akun_status, font=("Segoe UI", 9, "bold"),
                 bg=CARD, fg=AMBER).pack(anchor="w")

        # ===== QR Login =====
        ttk.Separator(pad).pack(fill="x", pady=(14, 8))
        tk.Label(pad, text="— atau login cepat via QR —", font=("Segoe UI", 10, "bold"),
                 bg=CARD, fg=TEXT).pack(anchor="w", pady=(0, 6))
        self.btn_qr = ttk.Button(pad, text="📲  Tampilkan QR Login", command=self._akun_qr_start)
        self.btn_qr.pack(anchor="w", pady=(0, 8))

        self.qr_canvas = tk.Canvas(pad, width=220, height=220, bg="white",
                                   highlightthickness=1, highlightbackground=BORDER)
        self.qr_canvas.pack(anchor="w")

    def _entry(self, parent, secret=False):
        return tk.Entry(parent, width=50, bg="#0b1526", fg=TEXT, insertbackground=TEXT,
                        relief="flat", font=("Segoe UI", 10),
                        highlightthickness=1, highlightbackground=BORDER,
                        highlightcolor=BLUE, show="*" if secret else None)

    def _api_creds(self):
        api_id = int(self.entries["API_ID"].get().strip() or 0)
        api_hash = self.entries["API_HASH"].get().strip()
        if not api_id or not api_hash:
            messagebox.showerror("Kurang", "API_ID dan API_HASH harus terisi di tab Config.")
            return None, None
        return api_id, api_hash

    def _akun_qr_start(self):
        api_id, api_hash = self._api_creds()
        if not api_id:
            return
        self.akun_status.set("⏳ Menyiapkan QR...")
        self.btn_qr.config(state="disabled")
        self.qr_canvas.delete("all")

        def work():
            try:
                from telethon.sessions import StringSession
                from telethon import TelegramClient
                client = TelegramClient(StringSession(), api_id, api_hash,
                                         flood_sleep_threshold=10)
                self._run(client.connect(), timeout=30)
                qr = self._run(client.qr_login(), timeout=30)
                self._akun_qr = qr
                self._akun_client = client
                self.root.after(0, self._akun_qr_show, qr.url)
            except Exception as e:
                self.root.after(0, self._akun_qr_fail, str(e))

        threading.Thread(target=work, daemon=True).start()

    def _akun_qr_show(self, url):
        try:
            import segno
            qr = segno.make(url, error="m")
            matrix = qr.matrix
            n = len(matrix)
            scale = min(210 // max(n, 1), 10)
            size = n * scale
            cx = 110 - size // 2
            cy = 110 - size // 2
            self.qr_canvas.delete("all")
            for y, row in enumerate(matrix):
                for x, cell in enumerate(row):
                    if cell:
                        self.qr_canvas.create_rectangle(
                            cx + x * scale, cy + y * scale,
                            cx + (x + 1) * scale, cy + (y + 1) * scale,
                            fill="black", outline="")
            self.akun_status.set("📲 Scan QR dengan Telegram HP: Settings → Devices → Scan QR")
            self._akun_wait_qr()
        except Exception as e:
            self._akun_qr_fail(f"Gagal rendering QR: {e}")

    def _akun_wait_qr(self):
        def work():
            try:
                me = self._run(self._akun_qr.wait(timeout=150), timeout=180)
                if self._akun_client is None:
                    return
                session = self._run(self._akun_client.session.save(), timeout=15)
                self._run(self._akun_client.disconnect(), timeout=15)
                self._akun_client = None
                self.root.after(0, self._akun_logged_in, session, me)
            except Exception as e:
                self.root.after(0, self._akun_qr_fail, f"QR timeout/dibatalkan: {e}")

        threading.Thread(target=work, daemon=True).start()

    def _akun_qr_fail(self, err):
        self.btn_qr.config(state="normal")
        self.akun_status.set(f"❌ {err}")
        self.qr_canvas.delete("all")

    def _akun_send_code(self):
        phone = self.akun_phone_entry.get().strip()
        if not phone:
            messagebox.showerror("Kurang", "Masukkan nomor HP dulu (mis. +628123456789).")
            return
        api_id = int(self.entries["API_ID"].get().strip() or 0)
        api_hash = self.entries["API_HASH"].get().strip()
        if not api_id or not api_hash:
            messagebox.showerror("Kurang", "API_ID dan API_HASH harus terisi di tab Config.")
            return
        self.akun_status.set("⏳ Menyambung...")
        self.btn_send_code.config(state="disabled")

        def work():
            try:
                from telethon.sessions import StringSession
                from telethon import TelegramClient
                client = TelegramClient(StringSession(), api_id, api_hash,
                                         flood_sleep_threshold=10)
                self._run(client.connect(), timeout=30)
                self._run(client.send_code_request(phone), timeout=30)
                self._akun_phone = phone
                self._akun_client = client
                self.root.after(0, self._akun_code_ready)
            except Exception as e:
                self.root.after(0, self._akun_fail, str(e))

        threading.Thread(target=work, daemon=True).start()

    def _akun_code_ready(self):
        self.akun_status.set("✅ Kode terkirim. Masukkan kode OTP lalu Login.")
        self.btn_send_code.config(state="normal")
        self.btn_login.config(state="normal")

    def _akun_fail(self, err):
        self.btn_send_code.config(state="normal")
        self.btn_login.config(state="disabled")
        self.akun_status.set(f"❌ Gagal: {err}")

    def _akun_login(self):
        code = self.akun_code_entry.get().strip()
        password = self.akun_pass_entry.get()
        if not code:
            messagebox.showerror("Kurang", "Masukkan kode OTP yang dikirim Telegram.")
            return
        self.akun_status.set("⏳ Login...")
        self.btn_login.config(state="disabled")

        def work():
            try:
                client, phone = self._akun_client, self._akun_phone
                if client is None:
                    raise RuntimeError("Sesi login hilang, coba kirim kode lagi.")
                from telethon.errors import SessionPasswordNeededError
                try:
                    self._run(client.sign_in(phone, code=code), timeout=30)
                except SessionPasswordNeededError:
                    if not password:
                        raise
                    self._run(client.sign_in(password=password), timeout=30)
                session = self._run(client.session.save(), timeout=15)
                me = self._run(client.get_me(), timeout=30)
                self._run(client.disconnect(), timeout=15)
                self._akun_client = None
                self.root.after(0, self._akun_logged_in, session, me)
            except SessionPasswordNeededError:
                self.root.after(0, self._akun_need_password)
            except Exception as e:
                self.root.after(0, self._akun_fail, str(e))

        threading.Thread(target=work, daemon=True).start()

    def _akun_need_password(self):
        self.btn_login.config(state="normal")
        self.akun_status.set("🔑 Akun pakai 2FA — isi password lalu Login lagi.")

    def _akun_logged_in(self, session, me):
        data = _load_env()
        data["STRING_SESSION"] = session
        _save_env(data)
        self.entries["STRING_SESSION"].delete(0, "end")
        self.entries["STRING_SESSION"].insert(0, session)
        name = getattr(me, "first_name", "") or getattr(me, "username", "akun")
        self.btn_login.config(state="normal")
        self.akun_status.set(f"🎉 Login berhasil: {name} ({getattr(me, 'id', '?')}). Session tersimpan.")

    # ---------- Run ----------
    def _run_command(self):
        if getattr(sys, "frozen", False):
            return [sys.executable, "--headless"]
        return [sys.executable, str(BASE_DIR / "UserBot.py"), "--headless"]

    def _start(self):
        if self.proc and self.proc.poll() is None:
            messagebox.showwarning("Berjalan", "Userbot sudah berjalan.")
            return
        try:
            (BASE_DIR / "data" / ".stop").unlink(missing_ok=True)
        except Exception:
            pass
        self._append_log("▶  Memulai userbot...\n")
        self.proc = subprocess.Popen(
            self._run_command(),
            cwd=str(BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            self.nb.select(2)
        except Exception:
            pass
        self._refresh_status()
        threading.Thread(target=self._read_output, daemon=True).start()
        threading.Thread(target=self._wait_proc, daemon=True).start()

    def _stop(self):
        if not self.proc or self.proc.poll() is not None:
            return
        try:
            (BASE_DIR / "data" / ".stop").write_text("1", encoding="utf-8")
        except Exception:
            pass
        self._append_log("⏹  Stop diminta (menunggu userbot keluar)...\n")
        self.status_var.set("○  Menghentikan...")
        self._set_dot(AMBER)

    def _read_output(self):
        try:
            for line in self.proc.stdout:
                self._append_log(line.rstrip() + "\n")
        except Exception:
            pass

    def _append_log(self, text):
        self.root.after(0, self._safe_append, text)

    def _safe_append(self, text):
        self.log_box.insert("end", text)
        self.log_box.see("end")

    def _wait_proc(self):
        code = self.proc.wait()
        try:
            (BASE_DIR / "data" / ".stop").unlink(missing_ok=True)
        except Exception:
            pass
        self.root.after(0, self._proc_done, code)

    def _proc_done(self, code):
        self._safe_append(f"\n[SYS] Userbot keluar (kode {code}).\n")
        self._refresh_status()

    # ---------- Log ----------
    def _build_log_tab(self, parent):
        box_wrap = tk.Frame(parent, bg=CARD)
        box_wrap.pack(fill="both", expand=True, padx=14, pady=14)
        self.log_box = scrolledtext.ScrolledText(
            box_wrap, bg="#0b1526", fg="#cbd5e1", insertbackground=TEXT,
            font=("Consolas", 10), relief="flat", wrap="word")
        self.log_box.pack(fill="both", expand=True)
        tk.Button(box_wrap, text="🗑  Bersihkan", command=lambda: self.log_box.delete("1.0", "end"),
                  bg=CARD, fg=MUTED, activebackground="#31415a", activeforeground="white",
                  relief="flat", cursor="hand2", font=("Segoe UI", 9, "bold")).pack(anchor="e", pady=(6, 0))


def run_panel():
    root = tk.Tk()
    root.option_add("*tearOff", False)
    PanelApp(root)
    root.mainloop()


if __name__ == "__main__":
    run_panel()