# -*- coding: utf-8 -*-
"""اختبارات تهيئة النشر: تطبيع رابط قاعدة البيانات وكشف منصة المضيف."""
from __future__ import annotations

import os

import pytest

from core.config import Settings


class TestDatabaseUrlNormalization:
    """Railway/Neon/Supabase يحقنون postgresql:// بلا مشغّل async."""

    def test_plain_postgresql_gets_asyncpg(self) -> None:
        s = Settings(DATABASE_URL="postgresql://user:pass@host:5432/db")
        assert s.DATABASE_URL == "postgresql+asyncpg://user:pass@host:5432/db"

    def test_legacy_postgres_scheme(self) -> None:
        s = Settings(DATABASE_URL="postgres://user:pass@host:5432/db")
        assert s.DATABASE_URL == "postgresql+asyncpg://user:pass@host:5432/db"

    def test_already_has_driver_is_untouched(self) -> None:
        url = "postgresql+asyncpg://user:pass@host:5432/db"
        assert Settings(DATABASE_URL=url).DATABASE_URL == url

    def test_sqlite_is_untouched(self) -> None:
        url = "sqlite+aiosqlite:///./data/app.db"
        assert Settings(DATABASE_URL=url).DATABASE_URL == url

    def test_railway_postgres_variable_style(self) -> None:
        """صيغة Railway النموذجية."""
        s = Settings(DATABASE_URL="postgresql://postgres:abc123@postgres.railway.internal:5432/railway")
        assert s.DATABASE_URL.startswith("postgresql+asyncpg://")
        assert "postgres.railway.internal" in s.DATABASE_URL


class TestPlatformDetection:
    """كشف PORT و RAILWAY_PUBLIC_DOMAIN."""

    def test_port_is_picked_up(self, monkeypatch) -> None:
        from app.bot import _detect_platform
        from core.config import settings

        monkeypatch.setenv("PORT", "8080")
        _detect_platform()
        assert settings.WEBHOOK_PORT == 8080

    def test_railway_domain_sets_webhook_and_miniapp(self, monkeypatch) -> None:
        from app.bot import _detect_platform
        from core.config import settings

        monkeypatch.setenv("RAILWAY_PUBLIC_DOMAIN", "myapp.up.railway.app")
        monkeypatch.setattr(settings, "MINIAPP_URL", "")
        monkeypatch.setattr(settings, "API_BASE_URL", "")
        monkeypatch.delenv("API_BASE_URL", raising=False)
        monkeypatch.delenv("RAILWAY_SERVICE_API_URL", raising=False)
        _detect_platform()
        assert settings.WEBHOOK_URL == "https://myapp.up.railway.app"
        # نخدم الصفحة من نطاق البوت نفسه: /app
        assert settings.MINIAPP_URL == "https://myapp.up.railway.app/app"

    def test_non_railway_env_is_ignored(self, monkeypatch) -> None:
        from app.bot import _detect_platform
        from core.config import settings

        monkeypatch.delenv("PORT", raising=False)
        monkeypatch.delenv("RAILWAY_PUBLIC_DOMAIN", raising=False)
        before_port = settings.WEBHOOK_PORT
        before_url = settings.WEBHOOK_URL
        _detect_platform()
        assert settings.WEBHOOK_PORT == before_port
        assert settings.WEBHOOK_URL == before_url

    def test_invalid_port_is_ignored(self, monkeypatch) -> None:
        from app.bot import _detect_platform
        from core.config import settings

        monkeypatch.setenv("PORT", "not-a-number")
        before = settings.WEBHOOK_PORT
        _detect_platform()
        assert settings.WEBHOOK_PORT == before


class TestHealthServer:
    """خادم الفحص الصحي — يمنع Railway من اعتبار الخدمة غير سليمة."""

    def test_health_endpoint_responds(self) -> None:
        import socket
        import time
        import urllib.request

        from app.bot import _start_health_server

        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]

        _start_health_server(port)
        time.sleep(0.6)

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as r:
            assert r.status == 200
            assert b'"status":"ok"' in r.read()

    def test_unknown_path_returns_404(self) -> None:
        import socket
        import time
        import urllib.error
        import urllib.request

        from app.bot import _start_health_server

        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]

        _start_health_server(port)
        time.sleep(0.6)

        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/nope", timeout=5)
            raise AssertionError("expected HTTP 404")
        except urllib.error.HTTPError as e:
            assert e.code == 404
