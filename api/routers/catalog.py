# -*- coding: utf-8 -*-
"""مسارات الكتالوج: الكورسات والمراحل والدروس."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.db import get_session
from core.models import CodeSample, Course, Language, Lesson, Stage

router = APIRouter(prefix="/api", tags=["catalog"])


@router.get("/languages")
async def list_languages(
    security_only: bool = False,
    session: AsyncSession = Depends(get_session),
):
    stmt = select(Language)
    if security_only:
        stmt = stmt.where(Language.is_security_relevant.is_(True))
    res = await session.execute(stmt.order_by(Language.name))
    return [
        {
            "slug": x.slug,
            "name": x.name,
            "name_ar": x.name_ar,
            "difficulty": x.difficulty,
            "security": x.is_security_relevant,
            "esoteric": x.is_esoteric,
        }
        for x in res.scalars().all()
    ]


@router.get("/courses")
async def list_courses(session: AsyncSession = Depends(get_session)):
    res = await session.execute(
        select(Course).where(Course.is_published.is_(True)).order_by(Course.order_index)
    )
    return [
        {
            "id": c.id,
            "slug": c.slug,
            "title": c.title,
            "track": c.track,
            "difficulty": c.difficulty,
            "icon": c.icon,
        }
        for c in res.scalars().all()
    ]


@router.get("/courses/{slug}")
async def course_detail(slug: str, session: AsyncSession = Depends(get_session)):
    res = await session.execute(select(Course).where(Course.slug == slug))
    course = res.scalar_one_or_none()
    if not course:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "الكورس غير موجود")
    stages = await session.execute(
        select(Stage).where(Stage.course_id == course.id).order_by(Stage.order_index)
    )
    return {
        "id": course.id,
        "slug": course.slug,
        "title": course.title,
        "description": course.description,
        "stages": [
            {"id": s.id, "slug": s.slug, "title": s.title, "order": s.order_index}
            for s in stages.scalars().all()
        ],
    }


def _code_payload(c: CodeSample) -> dict:
    return {
        "id": c.id,
        "language": c.language,
        "title": c.title,
        "code": c.code,
        "explanation": c.explanation,
        "expected_output": c.expected_output,
        "anatomy": c.anatomy or [],
        "usages": c.usages or [],
        "parameters": c.parameters or [],
        "returns": c.returns,
        "gotchas": c.gotchas or [],
        "security_notes": c.security_notes or [],
        "related": c.related or [],
        "tags": c.tags or [],
    }


@router.get("/lessons/{lesson_id}")
async def lesson_detail(lesson_id: int, session: AsyncSession = Depends(get_session)):
    lesson = await session.get(Lesson, lesson_id)
    if not lesson:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "الدرس غير موجود")
    codes = await session.execute(
        select(CodeSample).where(CodeSample.lesson_id == lesson_id).order_by(CodeSample.order_index)
    )
    return {
        "id": lesson.id,
        "title": lesson.title,
        "summary": lesson.summary,
        "objectives": lesson.objectives,
        "content_md": lesson.content_md,
        "difficulty": lesson.difficulty,
        "est_minutes": lesson.est_minutes,
        "status": lesson.status,
        "code_samples": [_code_payload(c) for c in codes.scalars().all()],
    }


@router.get("/codes/{code_id}")
async def code_detail(code_id: int, session: AsyncSession = Depends(get_session)):
    c = await session.get(CodeSample, code_id)
    if not c:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "الكود غير موجود")
    return _code_payload(c)
