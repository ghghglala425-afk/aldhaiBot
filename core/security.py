# -*- coding: utf-8 -*-
"""الأمان: تجزئة كلمات المرور (PBKDF2) + توكنات JWT.

لا نعتمد مكتبات خارجية للتجزئة — hashlib قياسي وموثوق.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import logging
import os
import secrets

import jwt

from core.config import settings

log = logging.getLogger("security")

_ITERATIONS = 240_000
_ALGO = "sha256"

# مفاتيح يعرفها أي قارئ للكود — تُرفض في الإنتاج.
_INSECURE_KEYS = {"", "change-me", "change-me-with-a-long-random-string"}
_MIN_KEY_BYTES = 32
_ephemeral_key: str | None = None


def secret_is_weak(key: str | None = None) -> bool:
    """هل مفتاح التوقيع افتراضي/قصير؟ (لا يصلح للإنتاج)."""
    raw = (settings.SECRET_KEY if key is None else key) or ""
    return raw.strip() in _INSECURE_KEYS or len(raw.encode("utf-8")) < _MIN_KEY_BYTES


def _jwt_key() -> str:
    """مفتاح توقيع JWT.

    في الإنتاج لا نوقّع أبدا بمفتاح افتراضي معروف (يمكن تزوير أي توكن به)؛
    إن كان المفتاح ضعيفا نولّد مفتاحا عشوائيا لهذه العملية ونسجّل خطأ واضحا.
    """
    global _ephemeral_key
    if not secret_is_weak():
        return settings.SECRET_KEY
    if settings.is_prod:
        if _ephemeral_key is None:
            _ephemeral_key = secrets.token_urlsafe(48)
            log.error(
                "SECRET_KEY ضعيف أو غير مضبوط في الإنتاج — تم توليد مفتاح مؤقت "
                "لهذه العملية. اضبط SECRET_KEY (32 بايتا على الأقل) كي تبقى "
                "جلسات التطبيق صالحة بعد إعادة التشغيل."
            )
        return _ephemeral_key
    return settings.SECRET_KEY


# ---------------------------------------------------------------------
#  كلمات المرور
# ---------------------------------------------------------------------
def hash_password(password: str) -> str:
    """يُرجع: pbkdf2_sha256$iterations$salt_hex$hash_hex"""
    if not password or len(password) < 6:
        raise ValueError("كلمة المرور يجب أن تكون 6 أحرف على الأقل")
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac(_ALGO, password.encode("utf-8"), salt, _ITERATIONS)
    return f"pbkdf2_{_ALGO}${_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iters, salt_hex, hash_hex = stored.split("$")
        if not scheme.startswith("pbkdf2_"):
            return False
        dk = hashlib.pbkdf2_hmac(
            _ALGO, password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters)
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


# ---------------------------------------------------------------------
#  التوكنات
# ---------------------------------------------------------------------
def new_opaque_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def create_access_token(user_id: int, extra: dict | None = None) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int(
            (now + dt.timedelta(minutes=settings.ACCESS_TOKEN_TTL_MIN)).timestamp()
        ),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, _jwt_key(), algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(
            token, _jwt_key(), algorithms=[settings.JWT_ALGORITHM]
        )
    except jwt.PyJWTError:
        return None


def new_certificate_code() -> str:
    return "CERT-" + secrets.token_hex(8).upper()
