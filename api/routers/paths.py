# -*- coding: utf-8 -*-
"""مسارات التعلم."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import current_user
from core import paths as svc
from core.db import get_session
from core.models import User

router = APIRouter(prefix="/api/paths", tags=["paths"])


@router.get("")
async def list_paths(
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    rows = await svc.list_paths(session)
    return [await svc.path_progress(session, user, p) for p in rows]


@router.get("/{slug}")
async def get_path(
    slug: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    path = await svc.get_path(session, slug)
    if not path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "المسار غير موجود")
    return await svc.path_progress(session, user, path)
