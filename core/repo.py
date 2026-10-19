# -*- coding: utf-8 -*-
"""مستودع العمليات (Repository) — دوال قاعدة بيانات جاهزة للاستخدام من API والبوت."""
from __future__ import annotations

import re
import datetime as dt
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.logging import get_logger
from core.models import (
    AuditLog,
    Progress,
    User,
    XpEvent,
)
from core.security import hash_password, verify_password

log = get_logger("core.repo")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,32}$")


def valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email or ""))


def valid_username(username: str) -> bool:
    return bool(_USERNAME_RE.match(username or ""))


async def get_user(session: AsyncSession, user_id: int) -> Optional[User]:
    return await session.get(User, user_id)


async def get_user_by_email(session: AsyncSession, email: str) -> Optional[User]:
    res = await session.execute(select(User).where(User.email == email.lower()))
    return res.scalar_one_or_none()


async def get_user_by_telegram(session: AsyncSession, telegram_id: int) -> Optional[User]:
    res = await session.execute(select(User).where(User.telegram_id == telegram_id))
    return res.scalar_one_or_none()


async def get_user_by_username(session: AsyncSession, username: str) -> Optional[User]:
    res = await session.execute(select(User).where(User.username == username))
    return res.scalar_one_or_none()


async def create_user(
    session: AsyncSession,
    *,
    email: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    telegram_id: Optional[int] = None,
    role: str = "student",
) -> User:
    user = User(
        email=email.lower() if email else None,
        username=username,
        pass_hash=hash_password(password) if password else None,
        telegram_id=telegram_id,
        role=role,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    await log_event(session, user.id, "user.create", {"email": email, "role": role})
    log.info("مستخدم جديد #%s (%s)", user.id, email or telegram_id)
    return user


async def register_email(
    session: AsyncSession, email: str, password: str, username: Optional[str] = None
) -> tuple[Optional[User], Optional[str]]:
    """يُرجع (المستخدم, رسالة الخطأ)."""
    if not valid_email(email):
        return None, "صيغة البريد غير صحيحة."
    if username and not valid_username(username):
        return None, "اسم المستخدم يجب أن يكون 3-32 حرفا/رقما/شرطة."
    if await get_user_by_email(session, email):
        return None, "البريد مسجّل مسبقا."
    if username and await get_user_by_username(session, username):
        return None, "اسم المستخدم محجوز."
    try:
        user = await create_user(
            session, email=email, password=password, username=username
        )
    except ValueError as e:
        return None, str(e)
    return user, None


async def authenticate(
    session: AsyncSession, email: str, password: str
) -> tuple[Optional[User], Optional[str]]:
    user = await get_user_by_email(session, email)
    if not user or not user.pass_hash:
        return None, "بيانات الدخول غير صحيحة."
    if not verify_password(password, user.pass_hash):
        return None, "بيانات الدخول غير صحيحة."
    if not user.is_active:
        return None, "الحساب معطّل."
    user.last_seen = dt.datetime.now(dt.timezone.utc)
    await session.commit()
    return user, None


async def link_telegram(session: AsyncSession, user: User, telegram_id: int) -> None:
    """يربط حساب تلجرام — يرفض اختطاف حساب مرتبط بحساب تلجرام آخر."""
    if user.telegram_id and user.telegram_id != telegram_id:
        raise PermissionError("هذا الحساب مرتبط بحساب تلجرام آخر.")
    other = await get_user_by_telegram(session, telegram_id)
    if other and other.id != user.id:
        raise PermissionError("حساب تلجرام هذا مرتبط بمستخدم آخر.")
    user.telegram_id = telegram_id
    await session.commit()


async def add_xp(session: AsyncSession, user: User, amount: int, reason: str, ref: str = "") -> None:
    user.xp = (user.xp or 0) + amount
    user.level = max(1, user.xp // 500 + 1)
    session.add(XpEvent(user_id=user.id, amount=amount, reason=reason, ref=ref))
    await session.commit()


async def stats(session: AsyncSession) -> dict:
    users = await session.scalar(select(func.count()).select_from(User))
    passed = await session.scalar(
        select(func.count()).select_from(Progress).where(Progress.status == "passed")
    )
    return {"users": users or 0, "lessons_passed": passed or 0}


async def log_event(
    session: AsyncSession, user_id: Optional[int], action: str, meta: dict | None = None
) -> None:
    session.add(AuditLog(user_id=user_id, action=action, meta=meta or {}))
    await session.commit()
