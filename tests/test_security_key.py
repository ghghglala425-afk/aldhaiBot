# -*- coding: utf-8 -*-
"""سلامة مفتاح توقيع JWT: لا توقيع بمفتاح افتراضي معروف في الإنتاج."""
from __future__ import annotations

import jwt
import pytest

from core import security
from core.config import settings


@pytest.fixture(autouse=True)
def _reset_key_cache(monkeypatch):
    monkeypatch.setattr(security, "_ephemeral_key", None)
    yield


def test_default_key_is_flagged_weak(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SECRET_KEY", "change-me")
    assert security.secret_is_weak() is True


def test_long_random_key_is_accepted(monkeypatch) -> None:
    key = "a" * 64
    monkeypatch.setattr(settings, "SECRET_KEY", key)
    assert security.secret_is_weak() is False
    assert security._jwt_key() == key


def test_production_never_signs_with_default_key(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SECRET_KEY", "change-me")
    monkeypatch.setattr(settings, "ENV", "production")

    first = security._jwt_key()
    assert first and first != "change-me"
    assert len(first.encode("utf-8")) >= 32
    # ثابت داخل نفس العملية كي تظل الجلسات صالحة
    assert security._jwt_key() == first


def test_production_rejects_token_forged_with_default_key(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SECRET_KEY", "")
    monkeypatch.setattr(settings, "ENV", "production")

    forged = jwt.encode({"sub": "1"}, "change-me", algorithm=settings.JWT_ALGORITHM)
    assert security.decode_access_token(forged) is None

    legit = security.create_access_token(7)
    payload = security.decode_access_token(legit)
    assert payload and payload["sub"] == "7"


def test_development_keeps_configured_key(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SECRET_KEY", "change-me")
    monkeypatch.setattr(settings, "ENV", "dev")
    assert security._jwt_key() == "change-me"
