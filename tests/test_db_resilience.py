# -*- coding: utf-8 -*-
"""اختبارات مرونة قاعدة البيانات: مضيف خاطئ، مرجع غير محلول، اختيار الرابط."""
from __future__ import annotations

from core.db import (
    SQLITE_FALLBACK,
    _host_resolvable,
    _url_host,
    choose_database_url,
    resolve_database_url,
)


class TestUrlHelpers:
    def test_url_host_extraction(self) -> None:
        assert _url_host("postgresql+asyncpg://u:p@db:5432/name") == "db"
        assert (
            _url_host("postgresql://u:p@postgres.railway.internal:5432/railway")
            == "postgres.railway.internal"
        )
        assert _url_host("sqlite+aiosqlite:///./data/app.db") == ""

    def test_host_resolvable_for_real_host(self) -> None:
        assert _host_resolvable("localhost") is True

    def test_host_not_resolvable(self) -> None:
        """المضيف الخاطئ (اسم خدمة Compose) لا يُحلّ."""
        assert _host_resolvable("definitely-not-a-real-host-xyz.invalid") is False

    def test_empty_host(self) -> None:
        assert _host_resolvable("") is False


class TestChooseDatabaseUrl:
    """الدالة خالصة: لا تلمس حالة المشروع."""

    def test_unset_falls_back_to_sqlite(self) -> None:
        url, reason = choose_database_url(None)
        assert url == SQLITE_FALLBACK
        assert reason == "unset"

    def test_empty_string_falls_back(self) -> None:
        url, reason = choose_database_url("   ")
        assert url == SQLITE_FALLBACK
        assert reason == "unset"

    def test_unresolved_railway_reference(self) -> None:
        url, reason = choose_database_url("${{Postgres.DATABASE_URL}}")
        assert url == SQLITE_FALLBACK
        assert reason == "unresolved-reference"

    def test_literal_reference_inside_url(self) -> None:
        url, reason = choose_database_url("postgresql://u:p@${{Postgres.DATABASE_URL}}/db")
        assert url == SQLITE_FALLBACK
        assert reason == "unresolved-reference"

    def test_compose_host_db_is_rejected(self) -> None:
        """«db» اسم خدمة Docker Compose — غير موجود على Railway."""
        url, reason = choose_database_url("postgresql://cyber:cyber@db:5432/cyberbot")
        assert url == SQLITE_FALLBACK
        assert reason.startswith("unresolvable-host")

    def test_railway_internal_host_is_kept(self) -> None:
        """مضيف داخلي لا يُحلّ محليا لكنه يُحلّ داخل Railway — لا يُحقَّن إلى SQLite."""
        url, reason = choose_database_url(
            "postgresql://u:p@postgres.railway.internal:5432/railway"
        )
        assert url == "postgresql+asyncpg://u:p@postgres.railway.internal:5432/railway"
        assert reason == "postgres"

    def test_valid_postgres_is_kept_and_normalised(self) -> None:
        url, reason = choose_database_url("postgresql://u:p@localhost:5432/db")
        assert url == "postgresql+asyncpg://u:p@localhost:5432/db"
        assert reason == "postgres"

    def test_sqlite_is_kept_as_is(self) -> None:
        url, reason = choose_database_url("sqlite+aiosqlite:///./data/app.db")
        assert url == "sqlite+aiosqlite:///./data/app.db"
        assert reason == "sqlite"

    def test_legacy_postgres_scheme(self) -> None:
        url, reason = choose_database_url("postgres://u:p@localhost:5432/db")
        assert url == "postgresql+asyncpg://u:p@localhost:5432/db"


class TestResolveDatabaseUrlUsesEnv:
    def test_reads_environment(self, monkeypatch) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert resolve_database_url() == SQLITE_FALLBACK

    def test_environment_postgres(self, monkeypatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
        assert resolve_database_url() == "postgresql+asyncpg://u:p@localhost:5432/db"


class TestSessionProxy:
    """الوكيل يسمح بتبديل المحرّك مع بقاء الاستيرادات المباشرة صالحة."""

    def test_proxy_is_callable(self) -> None:
        from core.db import SessionLocal

        assert callable(SessionLocal)

    def test_proxy_delegates_attributes(self) -> None:
        from core.db import SessionLocal

        assert hasattr(SessionLocal, "configure")

    def test_proxy_rebind_keeps_identity(self) -> None:
        from core.db import SessionLocal

        original = SessionLocal
        maker = SessionLocal._maker
        try:
            SessionLocal._set(maker)  # لا شيء يتغيّر
            assert SessionLocal is original
        finally:
            SessionLocal._set(maker)
