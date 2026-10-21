# -*- coding: utf-8 -*-
"""حواجز التوسّع: طابور تنفيذ، قاطع دائرة، حماية /diag، فشل DB الصريح."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

from core.config import settings
from core.db import MISSING_DB_URL, SQLITE_FALLBACK, choose_database_url
from pipeline import sandbox_runner as sb

ROOT = Path(__file__).resolve().parents[1]


class TestNoSilentSqliteInProd:
    def test_unset_without_fallback_is_not_sqlite(self) -> None:
        url, reason = choose_database_url(None, allow_fallback=False)
        assert url == MISSING_DB_URL
        assert reason == "unset"
        assert url != SQLITE_FALLBACK

    def test_unresolved_reference_without_fallback(self) -> None:
        url, reason = choose_database_url(
            "${{Postgres.DATABASE_URL}}", allow_fallback=False
        )
        assert url == MISSING_DB_URL
        assert reason == "unresolved-reference"

    def test_bad_host_stays_postgres(self) -> None:
        url, reason = choose_database_url(
            "postgresql://u:p@db:5432/name", allow_fallback=False
        )
        assert url.startswith("postgresql+asyncpg://")
        assert reason.startswith("unresolvable-host")

    def test_valid_postgres_not_flagged_as_misconfigured(self, monkeypatch) -> None:
        from core import db

        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
        monkeypatch.setattr(settings, "ALLOW_SQLITE_FALLBACK", False)
        assert db.resolve_database_url() == "postgresql+asyncpg://u:p@localhost:5432/db"
        assert db.fallback_reason() is None
        assert db.is_misconfigured() is False


class TestExecQueue:
    def test_queue_full_skips_fast(self, monkeypatch) -> None:
        monkeypatch.setattr(sb, "_EXEC_WAITING", settings.EXEC_QUEUE_MAX)
        res = asyncio.run(sb.run_code("python", "print(1)", exec_enabled=True))
        assert res.status == "skipped"
        assert "طابور" in res.detail

    def test_breaker_skips_without_calling_provider(self, monkeypatch) -> None:
        called = AsyncMock()
        monkeypatch.setattr(sb, "_EXEC_OPEN_UNTIL", time.monotonic() + 60)
        monkeypatch.setattr(sb, "remote_available", AsyncMock(return_value=True))
        monkeypatch.setattr(sb, "_run_judge0", called)
        res = asyncio.run(sb.run_code("python", "print(1)", exec_enabled=True))
        assert res.status == "skipped"
        assert "مشغولة" in res.detail
        called.assert_not_awaited()

    def test_transient_429_is_retried_once(self, monkeypatch) -> None:
        monkeypatch.setattr(sb, "_RETRY_DELAY", 0)
        monkeypatch.setattr(settings, "EXEC_PROVIDER", "judge0")
        monkeypatch.setattr(sb, "remote_available", AsyncMock(return_value=True))
        busy = sb.RunResult("skipped", "none", detail="مشغولة الآن (429)")
        ok = sb.RunResult("ok", "judge0", "4")
        runner = AsyncMock(side_effect=[busy, ok])
        monkeypatch.setattr(sb, "_run_judge0", runner)
        res = asyncio.run(sb.run_code("python", "print(4)", exec_enabled=True))
        assert res.status == "ok"
        assert runner.await_count == 2
        assert sb._EXEC_FAIL_STREAK == 0

    def test_breaker_opens_after_three_transient_failures(self, monkeypatch) -> None:
        monkeypatch.setattr(sb, "_RETRY_DELAY", 0)
        monkeypatch.setattr(settings, "EXEC_PROVIDER", "judge0")
        monkeypatch.setattr(sb, "remote_available", AsyncMock(return_value=True))
        busy = sb.RunResult("skipped", "none", detail="مشغولة الآن (429)")
        monkeypatch.setattr(sb, "_run_judge0", AsyncMock(return_value=busy))
        for _ in range(3):
            asyncio.run(sb.run_code("python", "print(1)", exec_enabled=True))
        assert sb._EXEC_OPEN_UNTIL > time.monotonic()


class TestDiagProtection:
    def test_diag_checks_token_and_prod(self) -> None:
        src = (ROOT / "app" / "bot.py").read_text(encoding="utf-8")
        assert "DIAG_TOKEN" in src
        assert "compare_digest" in src
        assert "settings.is_prod" in src

    def test_diag_hides_admin_ids(self) -> None:
        src = (ROOT / "app" / "bot.py").read_text(encoding="utf-8")
        assert '"admins": settings.admin_ids' not in src


class TestGenerationLimiter:
    def test_busy_when_queue_is_full(self, monkeypatch) -> None:
        from pipeline import jobs

        monkeypatch.setattr(jobs, "_now_waiting", settings.GEN_NOW_MAX_WAITING)

        async def _inner(*args, **kwargs):
            raise AssertionError("must not generate while busy")

        monkeypatch.setattr(jobs, "_generate_lesson_now_inner", _inner)
        res = asyncio.run(jobs.generate_lesson_now(1))
        assert res.get("busy") is True
