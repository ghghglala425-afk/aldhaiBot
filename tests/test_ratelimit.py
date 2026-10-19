# -*- coding: utf-8 -*-
"""اختبارات الحدّ المعدّل والبوابة الأمنية الجديدة."""
from __future__ import annotations

import pytest

from app import ratelimit


def setup_function() -> None:
    ratelimit.reset()


def test_allow_within_limit():
    for _ in range(ratelimit.LIMITS["ask"][0]):
        assert ratelimit.allow(1, "ask")


def test_blocks_after_limit_and_reports_wait():
    count, _ = ratelimit.LIMITS["ask"]
    for _ in range(count):
        ratelimit.allow(1, "ask")
    assert not ratelimit.allow(1, "ask")
    assert ratelimit.retry_in(1, "ask") >= 1


def test_buckets_are_per_user_and_per_key():
    count, _ = ratelimit.LIMITS["ask"]
    for _ in range(count):
        ratelimit.allow(1, "ask")
    assert not ratelimit.allow(1, "ask")
    assert ratelimit.allow(2, "ask")
    assert ratelimit.allow(1, "search")


def test_unknown_key_is_unlimited():
    for _ in range(1000):
        assert ratelimit.allow(1, "no-such-key")


def test_ai_configured_free_mode(monkeypatch):
    from core.config import Settings

    monkeypatch.setenv("AI_FREE_MODE", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("AI_API_KEY", "")
    s = Settings()
    assert s.ai_configured is True
    assert s.ai_mode == "free"
    assert "gemini" in s.free_providers


def test_admin_ids_parsing():
    from core.config import Settings

    s = Settings(ADMIN_IDS="12, 34, bad, 56")
    assert s.admin_ids == [12, 34, 56]


def test_free_mode_off_without_keys():
    from core.config import Settings

    s = Settings(AI_FREE_MODE=True, GEMINI_API_KEY="", GROQ_API_KEY="",
                 OPENROUTER_API_KEY="", AI_API_KEY="")
    assert s.ai_configured is False
    assert s.ai_mode == "off"
