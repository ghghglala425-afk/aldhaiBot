# -*- coding: utf-8 -*-
"""اعتماديات FastAPI المشتركة (المصادقة عبر Bearer)."""
from __future__ import annotations

from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import get_session
from core.models import User
from core.repo import get_user
from core.security import decode_access_token


async def current_user(
    authorization: Optional[str] = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "توكن مفقود")
    token = authorization.split(" ", 1)[1].strip()
    data = decode_access_token(token)
    if not data:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "توكن غير صالح أو منتهٍ")
    user = await get_user(session, int(data["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "الحساب غير متاح")
    return user


async def current_admin(user: User = Depends(current_user)) -> User:
    if user.role not in {"admin", "teacher"}:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "صلاحيات غير كافية")
    return user
