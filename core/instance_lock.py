# -*- coding: utf-8 -*-
"""قفل «نسخة واحدة» للـPolling عبر PostgreSQL.

سبب وجوده: عند كل نشر على Railway قد تعمل الحاوية الجديدة قبل أن تُغلق
القديمة، فتصبح نسختان تستدعيان `getUpdates` بالتوكن نفسه → تعارض مؤقت
(وفقدان/تكرار رسائل). القفل الاستشاري (advisory lock) يضمن أن نسخة واحدة
فقط تستقبل الرسائل، والبقية تنتظر بصمت مع بقاء `/health` جاهزا.

- PostgreSQL: قفل جلسة على اتصال مخصّص يبقى مفتوحا طوال عمر العملية.
- SQLite (تطوير محلي): لا قفل — عملية واحدة عادة.
- أي خطأ في القفل: نتابع (best-effort) حتى لا يتعطّل البوت بسبب القفل.
"""
from __future__ import annotations

import asyncio
import hashlib
import time

from sqlalchemy import text

from core.config import settings
from core.logging import get_logger

log = get_logger("core.instance_lock")

_lock_conn = None
_lock_key: int | None = None


def lock_key() -> int:
    """مفتاح ثابت لكل توكن بوت، ضمن نطاق bigint."""
    digest = hashlib.sha256((settings.BOT_TOKEN or "no-token").encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


async def acquire_polling_lock() -> bool:
    """يحاول حجز حق الـPolling. يعيد True إن أصبحنا النسخة النشطة."""
    global _lock_conn, _lock_key

    if _lock_conn is not None:
        return True
    if not settings.POLLING_LOCK_ENABLED:
        return True

    from core.db import engine

    if engine.url.get_backend_name() != "postgresql":
        return True

    key = lock_key()
    wait = int(settings.POLLING_LOCK_WAIT_SECONDS)
    started = time.monotonic()
    waiting_logged = False
    next_note = 60.0

    try:
        conn = await engine.connect()
    except Exception as e:  # noqa: BLE001
        log.warning("تعذّر فتح اتصال قفل النسخة (%s) — سنتابعة بلا قفل.", e)
        return True

    try:
        while True:
            try:
                acquired = await conn.scalar(
                    text("SELECT pg_try_advisory_lock(:key)"), {"key": key}
                )
            except Exception as e:  # noqa: BLE001
                log.warning("تعذّر أخذ قفل النسخة (%s) — سنتابعة بلا قفل.", e)
                await _safe_close(conn)
                return True

            if acquired:
                _lock_conn = conn
                _lock_key = key
                if waiting_logged:
                    log.info(
                        "أُغلق الاتصال بالنسخة السابقة بعد %.0f ثانية — بدء استقبال الرسائل.",
                        time.monotonic() - started,
                    )
                return True

            elapsed = time.monotonic() - started
            if not waiting_logged:
                waiting_logged = True
                log.warning(
                    "نسخة أخرى من البوت تستقبل الرسائل الآن — سننتظر إغلاقها "
                    "بدل إحداث تعارض (الخدمة تبقى سليمة على /health)."
                )
            elif elapsed >= next_note:
                log.info("ما زلنا ننتظر إغلاق النسخة الأخرى (%.0f ثانية)…", elapsed)
                next_note += 60.0

            if wait >= 0 and elapsed >= wait:
                log.error(
                    "انتهت مهلة انتظار قفل النسخة (%s ثانية) — سنتابعة رغم ذلك. "
                    "أوقف أي نسخة أخرى تعمل بنفس التوكن.",
                    wait,
                )
                await _safe_close(conn)
                return False

            await asyncio.sleep(2.0)
    except asyncio.CancelledError:
        await _safe_close(conn)
        raise


async def release_polling_lock() -> None:
    """يحرّر القفل عند الإغلاق (وإلا تحرّر تلقائيا بانتهاء العملية)."""
    global _lock_conn, _lock_key

    conn, key = _lock_conn, _lock_key
    _lock_conn, _lock_key = None, None
    if conn is None:
        return
    try:
        if key is not None:
            await conn.scalar(
                text("SELECT pg_advisory_unlock(:key)"), {"key": key}
            )
    except Exception as e:  # noqa: BLE001
        log.debug("تعذّر تحرير قفل النسخة صراحة (%s).", e)
    finally:
        await _safe_close(conn)


async def _safe_close(conn) -> None:
    try:
        await conn.close()
    except Exception:  # noqa: BLE001
        pass
