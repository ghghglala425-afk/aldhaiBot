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
    فحصه بالـ DNS محليا يعني تدهوراAlways إلى SQLite.
    """
    return host.endswith(".internal") or host.endswith(".railway.internal")


def choose_database_url(raw: str | None) -> tuple[str, str]:
    """يقرّر رابط قاعدة البيانات النهائي ويعيد (الرابط، سبب الاختيار).

    دوال خالصة — بلا حالة عامة — حتى يسهل اختبارها.
    """
    value = (raw or "").strip()
    if not value:
        return SQLITE_FALLBACK, "unset"
    if _has_unresolved_reference(value):
        return SQLITE_FALLBACK, "unresolved-reference"
    normalized = normalize_db_url(value)
    if _is_sqlite(normalized):
        return normalized, "sqlite"
    host = _url_host(normalized)
    if host and not _is_private_service_host(host) and not _host_resolvable(host):
        return SQLITE_FALLBACK, f"unresolvable-host:{host}"
    return normalized, "postgres"


def resolve_database_url() -> str:
    """يقرّر رابط قاعدة البيانات الفعلي حسب بيئة التشغيل."""
    url, reason = choose_database_url(os.environ.get("DATABASE_URL"))
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


async def _connect_with_retry() -> None:
    """يتصل بالقاعدة مع إعادة محاولة (الخدمة قد لا تكون جاهزة بعد الإقلاع)."""
    last: Exception | None = None
    for attempt in range(1, CONNECT_ATTEMPTS + 1):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                # توسيع الجداول الموجودة بأعمدة ناقصة (لا يفعلها create_all)
                await _apply_column_migrations(conn)
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
    global engine, _DATABASE_URL
    log.error(
        "تعذّر الوصول إلى PostgreSQL (%s) — التحويل إلى SQLite المحلي. "
        "تأكد من ضبط DATABASE_URL في Railway Variables.",
        reason,
    )
    await engine.dispose()
    _DATABASE_URL = SQLITE_FALLBACK
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
    """
    from sqlalchemy import inspect, text

    def _existing_columns(sync_conn, table: str) -> set[str]:
        insp = inspect(sync_conn)
        if table not in insp.get_table_names():
            return set()
        return {c["name"] for c in insp.get_columns(table)}

    # (الجدول، العمود، تعريفه في SQL)
    wanted = [
        ("lessons", "key_points", "JSON"),
        ("lessons", "memory_hook", "TEXT"),
        ("lessons", "prerequisites", "JSON"),
        ("lessons", "further_reading", "JSON"),
        ("lessons", "est_reading_minutes", "INTEGER DEFAULT 0"),
    ]

    for table, column, ddl in wanted:
        try:
            existing = await conn.run_sync(_existing_columns, table)
            if not existing or column in existing:
                # الجدول غير موجود (سيُنشأ بـ create_all) أو العمود موجود
                continue
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
            log.info("أُضيف العمود %s.%s", table, column)
        except Exception as e:  # noqa: BLE001
            log.debug("تعذّر إضافة العمود %s.%s: %s", table, column, e)


async def init_db() -> None:
    """إنشاء/تحديث الجداول (آمن ومتكرر بلا أثر جانبي)."""
    try:
        await _connect_with_retry()
        return
    except Exception as e:  # noqa: BLE001
        if _is_sqlite(_DATABASE_URL):
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
