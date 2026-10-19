# -*- coding: utf-8 -*-
"""اختبارات الزرع التلقائي وإعدادات اتصالات قاعدة البيانات."""
from __future__ import annotations

import asyncio
from pathlib import Path

from core.config import Settings


class TestPoolSettings:
    """ضبط حجم اتصالات PostgreSQL — مهم على Railway."""

    def test_defaults_are_conservative(self) -> None:
        s = Settings()
        assert s.DB_POOL_SIZE == 5
        assert s.DB_MAX_OVERFLOW == 5
        assert s.DB_POOL_TIMEOUT == 30
        assert s.DB_POOL_RECYCLE == 1800

    def test_total_connections_per_service(self) -> None:
        s = Settings()
        assert s.DB_POOL_SIZE + s.DB_MAX_OVERFLOW <= 10, (
            "the total per service must stay low on Railway (max_connections)"
        )

    def test_pool_kwargs_are_applied(self) -> None:
        from core.db import _engine_kwargs

        kwargs = _engine_kwargs("postgresql+asyncpg://u:p@localhost:5432/db")
        assert kwargs["pool_size"] == 5
        assert kwargs["max_overflow"] == 5
        assert kwargs["pool_timeout"] == 30
        assert kwargs["pool_recycle"] == 1800
        assert kwargs["pool_pre_ping"] is True

    def test_sqlite_has_no_pool_settings(self) -> None:
        from core.db import _engine_kwargs

        kwargs = _engine_kwargs("sqlite+aiosqlite:///./data/app.db")
        assert "pool_size" not in kwargs
        assert kwargs["connect_args"]["timeout"] == 30


def _reset_db() -> None:
    """يمسح كل الجداول ويعيد إنشاء المخطط (نفس نمط بقية الاختبارات)."""
    from core.db import engine, init_db
    from core.models import Base

    async def _drop_all() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    asyncio.run(_drop_all())
    asyncio.run(init_db())


class TestEnsureSeeded:
    """الزرع التلقائي عند إقلاع البوت/الـ API."""

    def test_empty_database_is_seeded(self) -> None:
        """قاعدة فارغة -> تُزرع تلقائيا (48 لغة + كورس)."""
        from pipeline.seed import ensure_seeded
        from sqlalchemy import func, select
        from core.db import SessionLocal
        from core.models import Course, Language

        _reset_db()
        try:
            seeded = asyncio.run(ensure_seeded())

            async def counts() -> tuple[int, int]:
                async with SessionLocal() as s:
                    langs = (await s.execute(select(func.count()).select_from(Language))).scalar()
                    courses = (await s.execute(select(func.count()).select_from(Course))).scalar()
                return langs, courses

            langs, courses = asyncio.run(counts())
            assert seeded is True, "the first call must seed"
            assert langs == 48, f"expected 48 languages, got {langs}"
            assert courses >= 1
        finally:
            _reset_db()

    def test_second_call_is_a_noop(self) -> None:
        """الزرع مرتين لا يكرر البيانات."""
        from pipeline.seed import ensure_seeded
        from sqlalchemy import func, select
        from core.db import SessionLocal
        from core.models import Language

        _reset_db()
        try:
            asyncio.run(ensure_seeded())
            second = asyncio.run(ensure_seeded())

            async def count() -> int:
                async with SessionLocal() as s:
                    return (await s.execute(select(func.count()).select_from(Language))).scalar()

            assert second is False, "second call must be a no-op"
            assert asyncio.run(count()) == 48, "no duplicate rows"
        finally:
            _reset_db()

    def test_languages_present_detection(self) -> None:
        from pipeline.seed import _languages_present, ensure_seeded

        _reset_db()
        try:
            assert asyncio.run(_languages_present()) is False
            asyncio.run(ensure_seeded())
            assert asyncio.run(_languages_present()) is True
        finally:
            _reset_db()

    def test_seed_uses_advisory_lock_on_postgres(self) -> None:
        """على PostgreSQL ناخذ قفلا استشاريا لمنع الزرع المتزامن."""
        src = Path("pipeline/seed.py").read_text(encoding="utf-8")
        assert "pg_advisory_lock" in src
        assert "pg_advisory_unlock" in src


class TestStartupIntegration:
    """التكامل مع إقلاع البوت والـ API."""

    def test_bot_post_init_calls_ensure_seeded(self) -> None:
        src = Path("app/bot.py").read_text(encoding="utf-8")
        assert "ensure_seeded" in src

    def test_api_lifespan_calls_ensure_seeded(self) -> None:
        src = Path("api/main.py").read_text(encoding="utf-8")
        assert "ensure_seeded" in src

    def test_seed_is_idempotent_by_design(self) -> None:
        """كل خطوة زرع تفحص الوجود قبل الإضافة."""
        src = Path("pipeline/seed.py").read_text(encoding="utf-8")
        assert src.count("exists") >= 5, "seed steps must check for existing rows"
