# -*- coding: utf-8 -*-
"""مسارات لوحة الإدارة (إحصاءات + فحص الصحة)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import current_admin
from core.db import get_session
from core.models import User
from core.repo import stats

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/stats")
async def admin_stats(
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(current_admin),
):
    return await stats(session)
