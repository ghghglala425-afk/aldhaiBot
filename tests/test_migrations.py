# -*- coding: utf-8 -*-
"""اختبار الترحيل الخفيف: إضافة الأعمدة الناقصة لجدول موجود."""
from __future__ import annotations

import asyncio

from sqlalchemy import text

from core.db import SessionLocal, engine, init_db


def _columns(table: str) -> set[str]:
    async def _read() -> set[str]:
        async with engine.begin() as conn:
            res = await conn.execute(text(f"PRAGMA table_info({table})"))
            return {row[1] for row in res.fetchall()}

    return asyncio.run(_read())


def test_missing_columns_are_added_to_existing_table() -> None:
    """جدول موجود بلا الأعمدة الجديدة → يجب أن تُضاف تلقائيا."""
    from core.models import Base

    async def _drop() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    # 1) أنشئ الجداول ثم احذف الأعمدة الجديدة يدويا (محاكاة قاعدة قديمة)
    asyncio.run(init_db())
    assert "key_points" in _columns("lessons"), "precondition: column should exist"

    async def _drop_columns() -> None:
        async with engine.begin() as conn:
            for col in ("key_points", "memory_hook", "prerequisites",
                        "further_reading", "est_reading_minutes"):
                await conn.execute(text(f"ALTER TABLE lessons DROP COLUMN {col}"))

    asyncio.run(_drop_columns())
    assert "key_points" not in _columns("lessons"), "precondition: column should be gone"

    # 2) أعد التهيئة — يجب أن تُضاف الأعمدة تلقائيا
    asyncio.run(init_db())

    cols = _columns("lessons")
    for col in ("key_points", "memory_hook", "prerequisites",
                "further_reading", "est_reading_minutes"):
        assert col in cols, f"migration did not add {col}"


def test_migration_is_idempotent() -> None:
    """إعادة التشغيل لا تكرّر ولا تفشل."""
    asyncio.run(init_db())
    asyncio.run(init_db())
    assert "key_points" in _columns("lessons")


def test_new_columns_have_defaults() -> None:
    """الأعمدة الجديدة لها قيم افتراضية (server_default) في قاعدة البيانات."""
    from core.models import Lesson

    table = Lesson.__table__
    for col in ("key_points", "prerequisites", "further_reading"):
        assert col in table.c
        assert table.c[col].server_default is not None, f"{col} needs a server default"
    assert table.c["est_reading_minutes"].server_default is not None
    assert table.c["memory_hook"].server_default is not None
