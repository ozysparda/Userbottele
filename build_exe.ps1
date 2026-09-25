# Build panel Userbottele menjadi .exe (Windows) dengan PyInstaller.
# Jalankan dari folder repo:  powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
# Hasil: dist\UserbotPanel.exe

$ErrorActionPreference = "Stop"

try {
    python -m PyInstaller --version | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "not installed" }
} catch {
    Write-Host "[!] PyInstaller belum terinstall. Install dulu:" -ForegroundColor Yellow
    Write-Host "    pip install pyinstaller"
    exit 1
}

$VERSION = "2.1.0"

if (-not (Test-Path "dist"))  { New-Item -ItemType Directory -Path "dist"  | Out-Null }

Write-Host "==> Building UserbotPanel.exe v$VERSION ..." -ForegroundColor Cyan

python -m PyInstaller --noconfirm --clean `
    --name "UserbotPanel" `
    --onefile `
    --windowed `
    --collect-all telethon `
    --exclude-module pytgcalls `
    --exclude-module pycryptodome `
    --paths "." `
    --add-data ".env.example;." `
    UserBot.py

if (-not (Test-Path "dist\UserbotPanel.exe")) {
    Write-Host "[X] Build gagal - dist\UserbotPanel.exe tidak ditemukan." -ForegroundColor Red
    exit 1
}

# Salin .env ke folder exe supaya mode frozen membaca config di folder sendiri
if (Test-Path ".env") {
    Copy-Item ".env" "dist\.env" -Force
    Write-Host "[OK] .env disalin ke dist\.env" -ForegroundColor Green
}

Write-Host ""
Write-Host "[OK] Build selesai: dist\UserbotPanel.exe" -ForegroundColor Green
Write-Host ""
Write-Host "TIPS:" -ForegroundColor Yellow
Write-Host "  - Panel dipakai LOKAL (PC kamu), bukan untuk GitHub Actions."
Write-Host "  - Letakkan .env di folder yang sama dengan UserbotPanel.exe, atau isi via tab Config di panel."
Write-Host "  - Userbot di Actions tetap jalan 24/7 seperti biasa; panel hanya akses ke akun sendiri."