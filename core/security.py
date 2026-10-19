# -*- coding: utf-8 -*-
"""الأمان: تجزئة كلمات المرور (PBKDF2) + توكنات JWT.

لا نعتمد مكتبات خارجية للتجزئة — hashlib قياسي وموثوق.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import os
import secrets

import jwt

from core.config import settings

_ITERATIONS = 240_000
_ALGO = "sha256"


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
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except jwt.PyJWTError:
        return None


def new_certificate_code() -> str:
    return "CERT-" + secrets.token_hex(8).upper()
