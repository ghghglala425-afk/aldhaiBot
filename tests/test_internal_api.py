# -*- coding: utf-8 -*-
"""تشغيل API الداخلية لخدمة Mini App من داخل حاوية البوت."""
from __future__ import annotations

from app import bot as botmod


def test_internal_api_base_uses_port(monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_API_PORT", "8123")
    assert botmod._internal_api_base() == "http://127.0.0.1:8123"


def test_internal_api_base_rejects_bad_port(monkeypatch) -> None:
    monkeypatch.setenv("INTERNAL_API_PORT", "abc")
    assert botmod._internal_api_base() == "http://127.0.0.1:8001"


def test_detect_platform_enables_internal_api(monkeypatch) -> None:
    from core.config import settings

    old_base = botmod._api_base
    old_enabled = botmod._internal_api_enabled
    old_mini = settings.MINIAPP_URL
    old_hook = settings.WEBHOOK_URL
    try:
        monkeypatch.setattr(settings, "API_BASE_URL", "")
        monkeypatch.setattr(settings, "MINIAPP_URL", "")
        monkeypatch.delenv("API_BASE_URL", raising=False)
        monkeypatch.setenv("RAILWAY_PUBLIC_DOMAIN", "bot.example.com")
        monkeypatch.setenv("INTERNAL_API_PORT", "8123")
        for key in list(__import__("os").environ):
            if key.startswith("RAILWAY_SERVICE_") and key.endswith("_URL"):
                monkeypatch.delenv(key, raising=False)
        botmod._detect_platform()
        assert botmod._internal_api_enabled is True
        assert botmod._api_base == "http://127.0.0.1:8123"
    finally:
        botmod._api_base = old_base
        botmod._internal_api_enabled = old_enabled
        settings.MINIAPP_URL = old_mini
        settings.WEBHOOK_URL = old_hook


def test_start_internal_api_builds_localhost_command(monkeypatch) -> None:
    calls: list[list[str]] = []

    class FakeProc:
        def terminate(self) -> None:
            pass

        def wait(self, timeout: float | None = None) -> int:
            return 0

        def kill(self) -> None:
            pass

    def fake_popen(cmd, env=None):  # noqa: ANN001
        calls.append(cmd)
        return FakeProc()

    import subprocess

    old_proc = botmod._internal_api_proc
    old_enabled = botmod._internal_api_enabled
    try:
        botmod._internal_api_proc = None
        botmod._internal_api_enabled = True
        monkeypatch.setenv("INTERNAL_API_PORT", "8123")
        monkeypatch.setattr(subprocess, "Popen", fake_popen)
        botmod._start_internal_api()
        assert calls, "لم تُشغّل العملية"
        cmd = calls[0]
        assert "uvicorn" in cmd and "api.main:app" in cmd
        assert cmd[cmd.index("--host") + 1] == "127.0.0.1"
        assert cmd[cmd.index("--port") + 1] == "8123"
    finally:
        botmod._internal_api_proc = old_proc
        botmod._internal_api_enabled = old_enabled
