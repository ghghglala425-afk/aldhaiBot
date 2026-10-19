# -*- coding: utf-8 -*-
"""المسارات التعلّمية: تجميع كورسات في رحلة واحدة + شهادة عند إكمالها."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import new_certificate_code
from core.models import Course, LearningPath, Lesson, PathCertificate, Progress, Stage, User
from core.learning import STATUS_PASSED


async def list_paths(session: AsyncSession) -> list[LearningPath]:
    res = await session.execute(select(LearningPath).order_by(LearningPath.order, LearningPath.id))
    return list(res.scalars())


async def get_path(session: AsyncSession, slug: str) -> LearningPath | None:
    return await session.scalar(select(LearningPath).where(LearningPath.slug == slug))


async def _lesson_ids(session: AsyncSession, slugs: list[str]) -> list[int]:
    if not slugs:
        return []
    course_ids = list(await session.scalars(select(Course.id).where(Course.slug.in_(slugs))))
    if not course_ids:
        return []
    res = await session.execute(
        select(Lesson.id).join(Stage, Stage.id == Lesson.stage_id).where(Stage.course_id.in_(course_ids))
    )
    return [r for r in res.scalars()]


async def _maybe_certificate(session: AsyncSession, user: User, path: LearningPath) -> PathCertificate:
    existing = await session.scalar(
        select(PathCertificate).where(PathCertificate.user_id == user.id, PathCertificate.path_id == path.id)
    )
    if existing:
        return existing
    cert = PathCertificate(user_id=user.id, path_id=path.id, code=new_certificate_code())
    session.add(cert)
    await session.commit()
    await session.refresh(cert)
    return cert


async def path_progress(session: AsyncSession, user: User, path: LearningPath) -> dict:
    ids = await _lesson_ids(session, list(path.course_slugs or []))
    total = len(ids)
    passed = 0
    if total:
        passed = await session.scalar(
            select(func.count()).select_from(Progress).where(
                Progress.user_id == user.id, Progress.lesson_id.in_(ids), Progress.status == STATUS_PASSED
            )
        ) or 0
    percent = round(passed / total * 100) if total else 0
    code = None
    if total and passed >= total:
        cert = await _maybe_certificate(session, user, path)
        code = cert.code
    return {
        "slug": path.slug,
        "title": path.title,
        "description": path.description,
        "icon": path.icon,
        "courses": list(path.course_slugs or []),
        "total": total,
        "passed": passed,
        "percent": percent,
        "certificate": code,
    }
