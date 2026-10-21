# -*- coding: utf-8 -*-
# تشغيل البوت فقط بلا Docker (Windows PowerShell).
# المتطلبات: Python 3.12 + LM Studio يعمل محليا (اختياري: بدونه يعمل البوت بلا توليد AI).
#
# أمثلة:
#   .\run_bot.ps1
#   .\run_bot.ps1 -NoSeed
#   .\run_bot.ps1 -Python "py -3.12"

param(
    [switch]$NoSeed,
    [switch]$Recreate,
    [string]$Python = "py -3.12",
    [string]$DatabaseUrl = "sqlite+aiosqlite:///./data/app.db"
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location -LiteralPath $root
$venv = Join-Path $root ".venv312"

Write-Host "== تشغيل بوت أكاديمية الأمن السيبراني والبرمجة (بلا Docker) ==" -ForegroundColor Cyan

# 1) ملف الإعدادات
if (-not (Test-Path -LiteralPath ".env")) {
    Copy-Item -LiteralPath ".env.example" -Destination ".env"
    Write-Host "[!] أُنشئ .env من .env.example — املأ BOT_TOKEN و AI_* ثم أعد التشغيل." -ForegroundColor Yellow
}

$envText = Get-Content -LiteralPath ".env" -Raw -Encoding UTF8
if ($envText -match "(?m)^\s*BOT_TOKEN\s*=\s*$") {
    Write-Host "[!] BOT_TOKEN فارغ في .env — البوت لن يبدأ." -ForegroundColor Red
}
if ($envText -match "(?m)^\s*AI_API_KEY\s*=\s*$") {
    if ($envText -match "(?m)^\s*AI_FREE_MODE\s*=\s*1") {
        Write-Host "[i] الوضع المجاني مفعّل — تأكد من GEMINI_API_KEY أو GROQ_API_KEY." -ForegroundColor Yellow
    } else {
        Write-Host "[i] AI_API_KEY فارغ — ستعمل الواجهة والتصفّح، لكن التوليد/المساعد الذكي معطّلان." -ForegroundColor Yellow
    }
}

# 2) البيئة الافتراضية
if ($Recreate -and (Test-Path -LiteralPath $venv)) {
    Write-Host "[*] حذف البيئة القديمة .venv312 ..."
    Remove-Item -LiteralPath $venv -Recurse -Force
}
if (-not (Test-Path -LiteralPath (Join-Path $venv "Scripts\python.exe"))) {
    Write-Host "[*] إنشاء البيئة الافتراضية .venv312 ..."
    $pyParts = $Python -split "\s+"
    $pyExe = $pyParts[0]
    $pyArgs = @()
    if ($pyParts.Length -gt 1) { $pyArgs = $pyParts[1..($pyParts.Length - 1)] }
    & $pyExe @pyArgs -m venv $venv
}
$py = Join-Path $venv "Scripts\python.exe"

# 3) الاعتماديات (مع تعافٍ من حجب إضافة SQLAlchemy على ويندوز)
Write-Host "[*] تثبيت الاعتماديات ..."
& $py -m pip install --upgrade pip --quiet
& $py -m pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host "[!] فشل التثبيت — إعادة المحاولة بلا إضافة C لـSQLAlchemy ..." -ForegroundColor Yellow
    & $py -m pip install --no-binary sqlalchemy "sqlalchemy>=2.0.30" --quiet
    & $py -m pip install -r requirements.txt --quiet
}

# 4) إعدادات التشغيل بلا Docker
$env:DISABLE_SQLALCHEMY_CEXT = "1"
if (-not $env:DATABASE_URL) { $env:DATABASE_URL = $DatabaseUrl }
if (-not $env:VERIFY_EXEC) { $env:VERIFY_EXEC = "0" }
Write-Host "[i] DATABASE_URL=$env:DATABASE_URL  VERIFY_EXEC=$env:VERIFY_EXEC"

# 5) البيانات الأساسية (اللغات والكورسات والمسارات)
if (-not $NoSeed) {
    Write-Host "[*] تهيئة البيانات الأساسية ..."
    & $py -m pipeline.seed
}

# 6) تشغيل البوت (Polling) — يشغّل معه عامل توليد المحتوى في الخلفية
Write-Host "[*] تشغيل البوت ... (Ctrl+C للإيقاف)" -ForegroundColor Green
& $py -m app.bot
