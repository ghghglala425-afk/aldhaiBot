# -*- coding: utf-8 -*-
"""مسارات بيئات الهدف (Targets): تشغيل/إيقاف الحاوية، وعرض المهام وتسليمها."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import current_user
from core import targets as svc
from core.db import get_session
from core.models import Lab, User

router = APIRouter(prefix="/api/labs", tags=["targets"])


class AnswerIn(BaseModel):
    answer: str


async def _lab(session: AsyncSession, lab_id: int) -> Lab:
    lab = await session.get(Lab, lab_id)
    if not lab or lab.kind != "target":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "بيئة الهدف غير موجودة")
    return lab


@router.get("/{lab_id}/target")
async def target_state(
    lab_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    lab = await _lab(session, lab_id)
    st = await svc.status(session, user, lab)
    tasks = await svc.task_state(session, user, lab)
    return {
        "id": lab.id,
        "title": lab.title,
        "description": lab.description,
        "image": lab.docker_image,
        "external_url": lab.external_url,
        "mode": st.get("mode", "docker"),
        "status": st["status"],
        "url": st["url"],
        **tasks,
    }


@router.post("/{lab_id}/target/start")
async def target_start(
    lab_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    lab = await _lab(session, lab_id)
    res = await svc.start(session, user, lab)
    if not res.get("ok"):
        msg = res.get("error") or "تعذّر التشغيل"
        if res.get("mode") == "guided":
            msg += " — يمكنك حل مهام البيئة (نمط موجّه) أو ضبط TARGET_EXTERNAL_URLS لهدف خارجي."
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, msg)
    return res


@router.post("/{lab_id}/target/stop")
async def target_stop(
    lab_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    lab = await _lab(session, lab_id)
    return await svc.stop(session, user, lab)


@router.post("/{lab_id}/target/tasks/{order}")
async def target_task(
    lab_id: int,
    order: int,
    body: AnswerIn,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    lab = await _lab(session, lab_id)
    return await svc.submit_task(session, user, lab, order, body.answer)
