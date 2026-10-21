# -*- coding: utf-8 -*-
"""اختبارات خدمة Mini App من نطاق البوت واكتشاف خدمة API."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from app import bot as botmod


class TestHelpers:
    def test_host_of(self) -> None:
        assert botmod._host_of("https://A.example.com/x?y=1") == "a.example.com"
        assert botmod._host_of("") == ""

    def test_explicit_api_base_wins(self, monkeypatch) -> None:
        monkeypatch.setattr(botmod.settings, "API_BASE_URL", "https://api.example.com/")
        monkeypatch.setenv("API_BASE_URL", "https://other.example.com")
        assert botmod._detect_api_base("bot.example.com", "") == "https://api.example.com"

    def test_railway_service_url(self, monkeypatch) -> None:
        monkeypatch.setattr(botmod.settings, "API_BASE_URL", "")
        monkeypatch.delenv("API_BASE_URL", raising=False)
        monkeypatch.setenv("RAILWAY_SERVICE_API_URL", "https://api.up.railway.app")
        found = botmod._detect_api_base("bot.up.railway.app", "")
        assert found == "https://api.up.railway.app"

    def test_miniapp_origin_fallback(self, monkeypatch) -> None:
        monkeypatch.setattr(botmod.settings, "API_BASE_URL", "")
        monkeypatch.delenv("API_BASE_URL", raising=False)
        monkeypatch.delenv("RAILWAY_SERVICE_API_URL", raising=False)
        found = botmod._detect_api_base(
            "bot.up.railway.app", "https://api.up.railway.app/app"
        )
        assert found == "https://api.up.railway.app"

    def test_no_api_found(self, monkeypatch) -> None:
        monkeypatch.setattr(botmod.settings, "API_BASE_URL", "")
        monkeypatch.delenv("API_BASE_URL", raising=False)
        monkeypatch.delenv("RAILWAY_SERVICE_API_URL", raising=False)
        assert botmod._detect_api_base("bot.example.com", "https://bot.example.com") == ""


class TestMiniAppUrlNormalization:
    def _detect(self, monkeypatch, mini: str) -> None:
        monkeypatch.setattr(botmod.settings, "MINIAPP_URL", mini)
        monkeypatch.setattr(botmod.settings, "API_BASE_URL", "")
        monkeypatch.setattr(botmod.settings, "WEBHOOK_URL", "")
        monkeypatch.setenv("RAILWAY_PUBLIC_DOMAIN", "bot.up.railway.app")
        monkeypatch.delenv("RAILWAY_ENVIRONMENT", raising=False)
        botmod._detect_platform()

    def test_external_domain_without_path_gets_app(self, monkeypatch) -> None:
        self._detect(monkeypatch, "https://api.up.railway.app")
        assert botmod.settings.MINIAPP_URL == "https://api.up.railway.app/app"

    def test_external_domain_with_path_kept(self, monkeypatch) -> None:
        self._detect(monkeypatch, "https://app.example.com/mini")
        assert botmod.settings.MINIAPP_URL == "https://app.example.com/mini"


@pytest.fixture(scope="module")
def base_url():
    state = botmod._start_health_server(0)
    assert state["role"] == "bot"
    server = botmod._health_server
    assert server is not None
    host, port = server.server_address[:2]
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


class TestMiniAppServed:
    def test_root_serves_html(self, base_url) -> None:
        with urllib.request.urlopen(base_url + "/", timeout=10) as r:
            body = r.read().decode("utf-8")
            assert r.status == 200
            assert "text/html" in (r.headers.get("Content-Type") or "")
        assert "<!DOCTYPE html>" in body
        assert "telegram-web-app.js" in body

    def test_app_path_serves_html(self, base_url) -> None:
        with urllib.request.urlopen(base_url + "/app", timeout=10) as r:
            assert r.status == 200
            assert "<!DOCTYPE html>" in r.read().decode("utf-8")

    def test_health_ok(self, base_url) -> None:
        with urllib.request.urlopen(base_url + "/health", timeout=10) as r:
            payload = json.loads(r.read())
        assert payload["status"] == "ok"

    def test_unknown_path_404(self, base_url) -> None:
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(base_url + "/nope", timeout=10)
        assert exc.value.code == 404
        assert json.loads(exc.value.read())["error"] == "not found"

    def test_api_without_base_is_clear_error(self, base_url, monkeypatch) -> None:
        monkeypatch.setattr(botmod, "_api_base", "")
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(base_url + "/api/auth/me", timeout=10)
        assert exc.value.code == 503
        payload = json.loads(exc.value.read())
        assert payload["error"] == "api_not_configured"
