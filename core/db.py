# -*- coding: utf-8 -*-
"""طبقة قاعدة البيانات (SQLAlchemy async + asyncpg، مع دعم SQLite للتشغيل بدون Docker)."""
from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from core.config import settings
from core.logging import get_logger
from core.models import Base

log = get_logger("core.db")


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


def _is_memory_sqlite(url: str) -> bool:
    return ":memory:" in url


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
    return {"pool_pre_ping": True, "pool_size": 10, "max_overflow": 20}


_DATABASE_URL = settings.DATABASE_URL
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

SessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def init_db() -> None:
    """إنشاء الجداول إن لم تكن موجودة (آمن ومتكرر بلا أثر جانبي)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info("تمت تهيئة قاعدة البيانات.")


async def get_session() -> AsyncIterator[AsyncSession]:
    """اعتمادية FastAPI لتوفير جلسة قاعدة بيانات."""
    async with SessionLocal() as session:
        yield session


async def close_db() -> None:
    await engine.dispose()
