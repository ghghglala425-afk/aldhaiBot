# -*- coding: utf-8 -*-
"""طبقة قاعدة البيانات (SQLAlchemy async + asyncpg، مع دعم SQLite للتشغيل بدون Docker).

المرونة:
- إذا لم يُضبط `DATABASE_URL` صراحةً → SQLite محلي (بلا خادم قاعدة).
- إذا كان الرابط يشير إلى مرجع Railway غير مُحلّ (${{...}}) → SQLite.
- إعادة محاولة الاتصال (الـ DB قد لا يكون جاهزا بعد الإقلاع).
- في حال تعذّر DNS على PostgreSQL → رجوع تلقائي إلى SQLite بدل الانهيار المتكرر.
"""
from __future__ import annotations

import asyncio
import os
import socket
from pathlib import Path
from typing import AsyncIterator

from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from core.config import normalize_db_url, settings
from core.logging import get_logger
from core.models import Base

log = get_logger("core.db")

# مسار SQLite الاحتياطي (يُستعمل على Railway Volume أو محليا)
SQLITE_FALLBACK = "sqlite+aiosqlite:///./data/app.db"
# رابط مقصود فاشل: يُستعمل في الإنتاج بدل SQLite عند غياب إعداد صحيح.
MISSING_DB_URL = "postgresql+asyncpg://invalid:invalid@127.0.0.1:1/missing"

# كم مرة نحاول الاتصال قبل إعطاء الأمل
CONNECT_ATTEMPTS = 6
CONNECT_BACKOFF = 2.0


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def _is_memory_sqlite(url: str) -> bool:
    return ":memory:" in url


def _has_unresolved_reference(url: str) -> bool:
    """Railway قد يبقي `${{Service.VAR}}` كسلسلة حرفية إذا لم يجد الخدمة."""
    return "${{" in url or "{{" in url


def _url_host(url: str) -> str:
    """يستخرج اسم المضيف من رابط قاعدة البيانات."""
    try:
        rest = url.split("://", 1)[1]
        rest = rest.split("@", 1)[-1]
        return rest.split(":", 1)[0].split("/", 1)[0]
    except Exception:  # noqa: BLE001
        return ""


def _is_private_service_host(host: str) -> bool:
    """مضيف خدمة داخلية (Railway/Nomad) — لا يُفحص بال DNS محليا.

    `postgres.railway.internal` لا يُحلّ خارج شبكة Railway، لكن يُحلّ داخلها.
    فحصه بالـ DNS محليا يعني تدهورا دائما إلى SQLite.
    """
    return host.endswith(".internal") or host.endswith(".railway.internal")


# سبب السقوط إلى SQLite (None = لا سقوط، القاعدة PostgreSQL)
_FALLBACK_REASON: str | None = None
# هل السقوط سببه خطأ في الإعداد (يستوجب تنبيها)
_FALLBACK_IS_MISCONFIG: bool = False


def fallback_reason() -> str | None:
    """سبب السقوط إلى SQLite إن حدث، وإلا None."""
    return _FALLBACK_REASON


def using_sqlite() -> bool:
    """هل تعمل الخدمة على SQLite؟"""
    return _DATABASE_URL.startswith("sqlite")


def is_misconfigured() -> bool:
    """هل السقوط إلى SQLite بسبب إعداد خاطئ (متغير ناقص/مرجع غير محلول)؟"""
    return _FALLBACK_IS_MISCONFIG


def choose_database_url(
    raw: str | None, *, allow_fallback: bool = True
) -> tuple[str, str]:
    """يقرّر رابط قاعدة البيانات النهائي ويعيد (الرابط، سبب الاختيار).

    دوال خالصة — بلا حالة عامة — حتى يسهل اختبارها.
    `allow_fallback=False` (الإنتاج): لا تحويل صامت إلى SQLite إطلاقا.
    """
    value = (raw or "").strip()
    if not value:
        return (SQLITE_FALLBACK, "unset") if allow_fallback else (MISSING_DB_URL, "unset")
    if _has_unresolved_reference(value):
        if allow_fallback:
            return SQLITE_FALLBACK, "unresolved-reference"
        return MISSING_DB_URL, "unresolved-reference"
    normalized = normalize_db_url(value)
    if _is_sqlite(normalized):
        return normalized, "sqlite"
    host = _url_host(normalized)
    if host and not _is_private_service_host(host) and not _host_resolvable(host):
        if allow_fallback:
            return SQLITE_FALLBACK, f"unresolvable-host:{host}"
        # يبقى PostgreSQL: إعادة المحاولة أفضل من الكتابة في قاعدة محلية مؤقتة.
        return normalized, f"unresolvable-host:{host}"
    return normalized, "postgres"


def resolve_database_url() -> str:
    """يقرّر رابط قاعدة البيانات الفعلي حسب بيئة التشغيل."""
    global _FALLBACK_REASON, _FALLBACK_IS_MISCONFIG

    allow = settings.ALLOW_SQLITE_FALLBACK
    url, reason = choose_database_url(
        os.environ.get("DATABASE_URL"), allow_fallback=allow
    )

    if reason == "sqlite":
        _FALLBACK_REASON = None
        _FALLBACK_IS_MISCONFIG = False
        return url
    if reason == "postgres":
        _FALLBACK_REASON = None
        _FALLBACK_IS_MISCONFIG = False
        return url

    _FALLBACK_REASON = reason
    _FALLBACK_IS_MISCONFIG = reason in {"unset", "unresolved-reference"} or reason.startswith(
        "unresolvable-host"
    )

    if not allow:
        _FALLBACK_REASON = f"disabled:{reason}"
        log.error(
            "إعداد قاعدة البيانات غير صالح (%s) و ALLOW_SQLITE_FALLBACK=0 — "
            "لن يُستعمل SQLite. اضبط DATABASE_URL في Railway Variables.",
            reason,
        )
        return url

    if reason == "unset":
        log.warning(
            "DATABASE_URL غير مضبوط — سيتم استعمال SQLite المحلي (%s). "
            "لاستعمال PostgreSQL اضبط DATABASE_URL في Variables.",
            url,
        )
    elif reason == "unresolved-reference":
        log.warning(
            "DATABASE_URL يحتوي مرجعا غير محلول — سيتم استعمال SQLite (%s).",
            url,
        )
    elif reason.startswith("unresolvable-host"):
        log.error(
            "مضيف قاعدة البيانات غير قابل للحل (DNS) — التحويل إلى SQLite بدل الانهيار. "
            "اضبط DATABASE_URL في Railway Variables (مثال: ${{Postgres.DATABASE_URL}})."
        )
    return url


def _host_resolvable(host: str) -> bool:
    """يفحص إن كان اسم المضيف قابلا للحل (DNS).

    على Railway قد يشير `DATABASE_URL` إلى مضيف غير موجود (مثل `db` وهو اسم
    خدمة Docker Compose) فينتج `socket.gaierror: Name or service not known`.
    """
    if not host:
        return False
    try:
        socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
        return True
    except socket.gaierror:
        return False
    except OSError:
        return False


def _ensure_sqlite_dir(url: str) -> None:
    """ينشئ مجلد ملف قاعدة SQLite إن لم يكن موجودا."""
    if not _is_sqlite(url) or _is_memory_sqlite(url):
        return
    raw = url.split(":///", 1)[-1]
    if not raw:
        return
    parent = Path(raw).expanduser().resolve().parent
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:  # noqa: BLE001
        log.warning("تعذّر إنشاء مجلد قاعدة البيانات %s: %s", parent, e)


def _engine_kwargs(url: str) -> dict:
    if _is_sqlite(url):
        if _is_memory_sqlite(url):
            return {"poolclass": StaticPool, "connect_args": {"check_same_thread": False}}
        # عدة كتّاب (البوت + عامل التوليد + API) على نفس الملف
        return {"connect_args": {"timeout": 30}}
    # PostgreSQL — حجم محدود عمدا: (pool_size + max_overflow) × الخدمات
    # يجب أن يبقى أقل من max_connections (خصوصا على Railway).
    return {
        "pool_pre_ping": True,
        "pool_size": settings.DB_POOL_SIZE,
        "max_overflow": settings.DB_MAX_OVERFLOW,
        "pool_timeout": settings.DB_POOL_TIMEOUT,
        "pool_recycle": settings.DB_POOL_RECYCLE,
    }


class _SessionMakerProxy:
    """وكيل لـ async_sessionmaker يسمح بتبديل المحرّك أثناء التشغيل.

    ضروري لأن بقية الوحدات تستورد `SessionLocal` مباشرة
    (`from core.db import SessionLocal`) — فالوكيل يبقى صالحا بعد التبديل.
    """

    __slots__ = ("_maker",)

    def __init__(self, maker) -> None:
        object.__setattr__(self, "_maker", maker)

    def _set(self, maker) -> None:
        object.__setattr__(self, "_maker", maker)

    def __call__(self, *args, **kwargs):
        return object.__getattribute__(self, "_maker")(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_maker"), name)


_DATABASE_URL = resolve_database_url()
_ensure_sqlite_dir(_DATABASE_URL)

engine = create_async_engine(_DATABASE_URL, echo=False, **_engine_kwargs(_DATABASE_URL))
log.info("محرّك قاعدة البيانات: %s", "SQLite" if _is_sqlite(_DATABASE_URL) else "PostgreSQL")

if _is_sqlite(_DATABASE_URL) and not _is_memory_sqlite(_DATABASE_URL):
    from sqlalchemy import event

    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # noqa: ANN001
        """WAL + busy_timeout: يمنع «database is locked» مع الكتابة المتزامنة."""
        cur = dbapi_conn.cursor()
        try:
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA busy_timeout=10000")
            cur.execute("PRAGMA foreign_keys=ON")
        finally:
            cur.close()

SessionLocal = _SessionMakerProxy(
    async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
)


async def _ensure_indexes(conn) -> None:
    """فهارس الاستعلامات الساخنة (آمنة ومتكررة) — تُسرّع التصفّح مع آلاف الدروس."""
    from sqlalchemy import text

    statements = (
        "CREATE INDEX IF NOT EXISTS ix_stages_course_id ON stages (course_id)",
        "CREATE INDEX IF NOT EXISTS ix_lessons_stage_id ON lessons (stage_id)",
        "CREATE INDEX IF NOT EXISTS ix_lessons_status ON lessons (status)",
        "CREATE INDEX IF NOT EXISTS ix_lessons_language_status "
        "ON lessons (language_slug, status)",
        "CREATE INDEX IF NOT EXISTS ix_questions_quiz_id ON questions (quiz_id)",
        "CREATE INDEX IF NOT EXISTS ix_options_question_id ON options (question_id)",
        "CREATE INDEX IF NOT EXISTS ix_attempts_user_quiz ON attempts (user_id, quiz_id)",
        "CREATE INDEX IF NOT EXISTS ix_answers_attempt_id ON answers (attempt_id)",
        "CREATE INDEX IF NOT EXISTS ix_lesson_assets_lesson_id "
        "ON lesson_assets (lesson_id)",
        "CREATE INDEX IF NOT EXISTS ix_code_samples_lesson_id "
        "ON code_samples (lesson_id)",
        "CREATE INDEX IF NOT EXISTS ix_generation_jobs_status_created "
        "ON generation_jobs (status, created_at)",
    )
    for sql in statements:
        try:
            await conn.execute(text(sql))
        except Exception as e:  # noqa: BLE001
            # جدول قديم/غائب لا يجب أن يمنع الإقلاع.
            log.warning("تعذّر إنشاء فهرس (%s): %s", sql.split(" ON ")[0], e)


async def _connect_with_retry() -> None:
    """يتصل بالقاعدة مع إعادة محاولة (الخدمة قد لا تكون جاهزة بعد الإقلاع)."""
    last: Exception | None = None
    for attempt in range(1, CONNECT_ATTEMPTS + 1):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                # توسيع الجداول الموجودة بأعمدة ناقصة (لا يفعلها create_all)
                await _apply_column_migrations(conn)
                await _ensure_indexes(conn)
            log.info("تمت تهيئة قاعدة البيانات.")
            return
        except (OperationalError, DBAPIError) as e:
            last = e
            if attempt >= CONNECT_ATTEMPTS:
                break
            wait = CONNECT_BACKOFF * attempt
            log.warning(
                "تعذّر الاتصال بقاعدة البيانات (%s/%s): %s — إعادة المحاولة خلال %ss",
                attempt, CONNECT_ATTEMPTS, e.__class__.__name__, wait,
            )
            await asyncio.sleep(wait)
    raise last if last else RuntimeError("تعذّر الاتصال بقاعدة البيانات")


async def _fallback_to_sqlite(reason: str) -> None:
    """ينتقل إلى SQLite عندما يتعذّر الوصول إلى PostgreSQL (مضيف غير معروف)."""
    global engine, _DATABASE_URL, _FALLBACK_REASON, _FALLBACK_IS_MISCONFIG

    log.error(
        "تعذّر الوصول إلى PostgreSQL (%s) — التحويل إلى SQLite المحلي. "
        "تأكد من ضبط DATABASE_URL في Railway Variables.",
        reason,
    )
    await engine.dispose()
    _DATABASE_URL = SQLITE_FALLBACK
    _FALLBACK_REASON = f"unreachable:{reason}"
    _FALLBACK_IS_MISCONFIG = True
    _ensure_sqlite_dir(_DATABASE_URL)
    engine = create_async_engine(_DATABASE_URL, echo=False, **_engine_kwargs(_DATABASE_URL))
    SessionLocal._set(
        async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    )
    log.warning("تم التحويل إلى SQLite: %s", _DATABASE_URL)


async def _apply_column_migrations(conn) -> None:
    """يضيف الأعمدة الناقصة إلى الجداول الموجودة.

    `create_all()` لا يضيف أعمدة جديدة لجدول قائم — والقاعدة على Railway
    استُعملت من قبل، فيجب توسيع جدول `lessons` يدويا.

    نقرأ الأعمدة مباشرة من information_schema (لا من الـ inspector الذي
    تخزن ذاكرته المؤقتة نتائجه القديمة) ونضيف كل عمود ناقص على حدة.
    """
    from sqlalchemy import text

    # (الجدول، العمود، تعريفه في SQL)
    wanted = [
        ("lessons", "key_points", "JSON NOT NULL DEFAULT '[]'"),
        ("lessons", "memory_hook", "TEXT NOT NULL DEFAULT ''"),
        ("lessons", "prerequisites", "JSON NOT NULL DEFAULT '[]'"),
        ("lessons", "further_reading", "JSON NOT NULL DEFAULT '[]'"),
        ("lessons", "est_reading_minutes", "INTEGER NOT NULL DEFAULT 0"),
        ("progress", "started_at", "TIMESTAMP"),
    ]

    is_pg = not _DATABASE_URL.startswith("sqlite")

    async def _columns(table: str) -> set[str]:
        if is_pg:
            sql = text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = :t"
            )
        else:
            sql = text(f"PRAGMA table_info({table})")
        res = await conn.execute(sql, {"t": table})
        rows = res.fetchall()
        if is_pg:
            return {r[0] for r in rows}
        return {r[1] for r in rows}

    for table, column, ddl in wanted:
        try:
            existing = await _columns(table)
            if not existing:
                # الجدول غير موجود — سيُنشأ عبر create_all بكل أعمدته
                continue
            if column in existing:
                continue
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
            log.warning("مُرحّل: أُضيف العمود %s.%s", table, column)
        except Exception as e:  # noqa: BLE001
            log.warning("تعذّر إضافة العمود %s.%s: %s", table, column, e)

    # معرّفات تلجرام قد تتجاوز 2^31 (int32) فتسبب:
    #   invalid input for query argument $1: ... (value out of int32 range)
    # نوسّع العمود القائم إلى BIGINT مرة واحدة (create_all لا يعدّل الأنواع).
    try:
        if is_pg:
            res = await conn.execute(
                text(
                    "SELECT data_type FROM information_schema.columns "
                    "WHERE table_name = 'users' AND column_name = 'telegram_id'"
                )
            )
            row = res.first()
            if row and str(row[0]).lower() in {"integer", "smallint"}:
                await conn.execute(
                    text("ALTER TABLE users ALTER COLUMN telegram_id TYPE BIGINT")
                )
                log.warning("مُرحّل: وُسّع users.telegram_id إلى BIGINT")
    except Exception as e:  # noqa: BLE001
        log.warning("تعذّر توسيع users.telegram_id إلى BIGINT: %s", e)


async def init_db() -> None:
    """إنشاء/تحديث الجداول (آمن ومتكرر بلا أثر جانبي)."""
    try:
        await _connect_with_retry()
        return
    except Exception as e:  # noqa: BLE001
        if _is_sqlite(_DATABASE_URL) or not settings.ALLOW_SQLITE_FALLBACK:
            raise
        # خطأ DNS/شبكة غالبا = إعداد خاطئ للمضيف
        await _fallback_to_sqlite(str(e))
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        log.info("تمت تهيئة قاعدة البيانات (SQLite الاحتياطية).")


async def get_session() -> AsyncIterator[AsyncSession]:
    """اعتمادية FastAPI لتوفير جلسة قاعدة بيانات."""
    async with SessionLocal() as session:
        yield session


async def close_db() -> None:
    await engine.dispose()
