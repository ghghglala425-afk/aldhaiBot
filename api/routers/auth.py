# -*- coding: utf-8 -*-
"""مسارات المصادقة: تسجيل، دخول، /me."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import current_user
from core.db import get_session
from core.models import User
from core.repo import authenticate, get_user_by_telegram, register_email
from core.security import create_access_token
from core.telegram_auth import verify_init_data

router = APIRouter(prefix="/api/auth", tags=["auth"])


class TelegramIn(BaseModel):
    init_data: str


class RegisterIn(BaseModel):
    email: str
    password: str = Field(min_length=6)
    username: str | None = None


class LoginIn(BaseModel):
    email: str
    password: str


class TokenOut(BaseModel):
    token: str
    user_id: int
    role: str


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterIn, session: AsyncSession = Depends(get_session)):
    user, err = await register_email(session, body.email, body.password, body.username)
    if err:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, err)
    assert user is not None
    return TokenOut(token=create_access_token(user.id), user_id=user.id, role=user.role)


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, session: AsyncSession = Depends(get_session)):
    user, err = await authenticate(session, body.email, body.password)
    if err or not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, err or "فشل الدخول")
    return TokenOut(token=create_access_token(user.id), user_id=user.id, role=user.role)


@router.post("/telegram", response_model=TokenOut)
async def telegram_login(body: TelegramIn, session: AsyncSession = Depends(get_session)):
    data = verify_init_data(body.init_data)
    if not data:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "بيانات تلجرام غير صالحة")
    tg_id = int(data.get("id"))
    user = await get_user_by_telegram(session, tg_id)
    if not user:
        # التسجيل إلزامي: لا إنشاء تلقائي من داخل التطبيق
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "لا يوجد حساب مرتبط. أنشئ حسابا من البوت عبر /register أولا.",
        )
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "الحساب معطّل")
    return TokenOut(token=create_access_token(user.id), user_id=user.id, role=user.role)


@router.get("/me")
async def me(user: User = Depends(current_user)):
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "role": user.role,
        "xp": user.xp,
        "level": user.level,
        "streak": user.streak_count,
        "telegram_linked": user.telegram_id is not None,
    }
