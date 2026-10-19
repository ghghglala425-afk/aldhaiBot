#!/bin/sh
# =============================================================================
#  نقطة الدخول الموحّدة (Docker / Railway / Compose)
#
#  APP_ROLE=bot  (الافتراضي) → يشغّل بوت تلجرام
#  APP_ROLE=api              → يشغّل واجهة FastAPI
#
#  المنفذ: $PORT على Railway، 8000 افتراضيا محليا
# =============================================================================
set -e

ROLE="${APP_ROLE:-bot}"
PORT_TO_USE="${PORT:-8000}"

if [ "$ROLE" = "api" ]; then
    echo "▶ تشغيل واجهة API على المنفذ ${PORT_TO_USE}"
    exec uvicorn api.main:app --host 0.0.0.0 --port "${PORT_TO_USE}"
fi

echo "▶ تشغيل بوت تلجرام (Polling) — المنفذ ${PORT_TO_USE} (خادم الفحص الصحي)"
exec python -m app.bot
