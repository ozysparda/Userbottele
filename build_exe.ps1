# Build panel Userbottele menjadi .exe (Windows) dengan PyInstaller.
# Jalankan dari folder repo:  powershell -ExecutionPolicy Bypass -File .\build_exe.ps1
# Hasil: dist\UserbotPanel.exe

$ErrorActionPreference = "Stop"

if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
    Write-Host "[!] PyInstaller belum terinstall. Install dulu:" -ForegroundColor Yellow
    Write-Host "    pip install pyinstaller"
    exit 1
}

$VERSION = "2.1.0"
$VER = $VERSION.Replace(".", ",")

if (-not (Test-Path "build")) { New-Item -ItemType Directory -Path "build" | Out-Null }
if (-not (Test-Path "dist"))  { New-Item -ItemType Directory -Path "dist"  | Out-Null }

# Version resource supaya Windows menampilkan versi di properties
$verFile = "build\ver.txt"
@"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($VER), prodvers=($VER),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904b0', [StringStruct('CompanyName','Userbottele'),
    StringStruct('FileDescription','Userbot Panel'), StringStruct('FileVersion','$VERSION'),
    StringStruct('InternalName','UserbotPanel'), StringStruct('OriginalFilename','UserbotPanel.exe'),
    StringStruct('ProductName','UserbotPanel'), StringStruct('ProductVersion','$VERSION')])]),
  VarFileInfo([VarStruct('Translation',[1033,1200])])]
"@ | Out-File -FilePath $verFile -Encoding ascii

Write-Host "==> Building UserbotPanel.exe v$VERSION ..." -ForegroundColor Cyan

pyinstaller --noconfirm --clean `
    --name "UserbotPanel" `
    --onefile `
    --windowed `
    --icon NONE `
    --version-file "build\ver.txt" `
    --collect-all telethon `
    --exclude-module pytgcalls `
    --exclude-module pycryptodome `
    --exclude-module aiohttp `
    --paths "." `
    --add-data ".env.example;." `
    UserBot.py

if (-not (Test-Path "dist\UserbotPanel.exe")) {
    Write-Host "[X] Build gagal - dist\UserbotPanel.exe tidak ditemukan." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "[OK] Build selesai: dist\UserbotPanel.exe" -ForegroundColor Green
Write-Host ""
Write-Host "TIPS:" -ForegroundColor Yellow
Write-Host "  - Panel dipakai LOKAL (PC kamu), bukan untuk GitHub Actions."
Write-Host "  - Letakkan .env di folder yang sama dengan UserbotPanel.exe, atau isi via tab Config di panel."
Write-Host "  - Userbot di Actions tetap jalan 24/7 seperti biasa; panel hanya akses ke akun sendiri."