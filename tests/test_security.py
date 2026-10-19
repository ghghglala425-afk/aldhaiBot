# -*- coding: utf-8 -*-
"""اختبارات الأمان الأساسية (بدون قاعدة بيانات)."""
from core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_password_roundtrip():
    h = hash_password("Secret123")
    assert verify_password("Secret123", h)
    assert not verify_password("wrong", h)


def test_password_rejects_short():
    try:
        hash_password("123")
    except ValueError:
        assert True
    else:
        assert False


def test_token_roundtrip():
    token = create_access_token(42)
    data = decode_access_token(token)
    assert data and data["sub"] == "42"


def test_token_invalid():
    assert decode_access_token("not-a-token") is None
