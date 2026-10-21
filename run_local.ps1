# -*- coding: utf-8 -*-
# تشغيل المنصّة محليا بدون Docker (Windows PowerShell).
# الاستخدام:  .\run_local.ps1
#            .\run_local.ps1 -NoSeed        (تخطي زرع البيانات)
#            .\run_local.ps1 -ApiOnly       (تشغيل الـAPI فقط)
#            .\run_local.ps1 -BotOnly       (تشغيل البوت فقط)

param(
    [switch]$NoSeed,
    [switch]$ApiOnly,
    [switch]$BotOnly,
    [string]$Python = "py -3.12"
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location -LiteralPath $root

Write-Host "== منصّة الأكاديمية — تشغيل محلي بدون Docker ==" -ForegroundColor Cyan

# 1) ملف الإعدادات
if (-not (Test-Path -LiteralPath ".env")) {
    Copy-Item -LiteralPath ".env.example" -Destination ".env"
    Write-Host "[!] أُنشئ .env من .env.example — املأ BOT_TOKEN و AI_API_KEY ثم أعد التشغيل." -ForegroundColor Yellow
}

# 2) بيئة افتراضية
if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe") -and -not (Test-Path -LiteralPath ".venv312\Scripts\python.exe")) {
    Write-Host "[*] إنشاء بيئة افتراضية .venv ..."
    $pyParts = $Python -split "\s+"
    $pyExe = $pyParts[0]
    $pyArgs = @()
    if ($pyParts.Length -gt 1) { $pyArgs = $pyParts[1..($pyParts.Length - 1)] }
    & $pyExe @pyArgs -m venv .venv
}
if (Test-Path -LiteralPath ".venv312\Scripts\python.exe") { $py = Join-Path $root ".venv312\Scripts\python.exe" } else { $py = Join-Path $root ".venv\Scripts\python.exe" }

# 3) تثبيت المتطلبات
Write-Host "[*] تثبيت المتطلبات ..."
& $py -m pip install --upgrade pip --quiet
& $py -m pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host "[!] فشل التثبيت العادي — إعادة المحاولة بنسخة SQLAlchemy غير المترجمة." -ForegroundColor Yellow
    & $py -m pip install --no-binary sqlalchemy sqlalchemy --quiet
    & $py -m pip install -r requirements.txt --quiet
}

# 4) متغيرات بيئة آمنة بدون Docker
$env:DISABLE_SQLALCHEMY_CEXT = "1"
if (-not $env:DATABASE_URL) { $env:DATABASE_URL = "sqlite+aiosqlite:///./data/app.db" }
if (-not $env:VERIFY_EXEC) { $env:VERIFY_EXEC = "0" }
Write-Host "[i] DATABASE_URL=$env:DATABASE_URL  VERIFY_EXEC=$env:VERIFY_EXEC"

# 5) زرع البيانات
if (-not $NoSeed) {
    Write-Host "[*] زرع البيانات الأولية ..."
    & $py -m pipeline.seed
}

# 6) التشغيل
if (-not $BotOnly) {
    Write-Host "[*] تشغيل الـAPI على http://localhost:8000/app (نافذة جديدة) ..." -ForegroundColor Green
    Start-Process -FilePath $py -ArgumentList "-m", "api.main" -WorkingDirectory $root
}
if (-not $ApiOnly) {
    Write-Host "[*] تشغيل البوت (polling) في هذه النافذة ..." -ForegroundColor Green
    & $py -m app.bot
}
