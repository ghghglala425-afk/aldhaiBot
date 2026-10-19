@echo off
chcp 65001 >nul
title Cyber Academy - تشغيل المنصة
cd /d "%~dp0"

echo ========================================================
echo   أكاديمية الأمن السيبراني والبرمجة - التشغيل
echo ========================================================
echo.

if not exist ".env" (
    echo [*] لا يوجد ملف .env - سيتم إنشاؤه من .env.example
    copy ".env.example" ".env" >nul
    echo [!] افتح ملف .env وضع BOT_TOKEN و AI_API_KEY ثم أعد التشغيل.
    pause
    exit /b
)

findstr /C:"BOT_TOKEN=" ".env" | findstr /R "BOT_TOKEN=." >nul
if errorlevel 1 (
    echo [!] BOT_TOKEN فارغ في .env - الرجاء ضبطه أولا.
    pause
    exit /b
)

echo [*] تشغيل الحاويات...
docker compose up --build -d

echo.
echo [+] تم التشغيل. الخدمات:
echo     - API:  http://localhost:8000/docs
echo     - البوت: افتح تلجرام واكتب /start
echo.
echo [*] لتعبئة بيانات أولية (لغة + كورس تجريبي):
echo     docker compose exec api python -m pipeline.seed
echo.
echo [i] لإيقاف كل شيء:  docker compose down
pause
