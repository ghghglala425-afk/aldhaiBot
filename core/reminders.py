# -*- coding: utf-8 -*-
"""التذكيرات الدراسية: من غاب عن درسه 23 ساعة يُذكَّر بالدرس الذي توقف عنده.

المنطق:
- نعتبر آخر ``Progress.updated_at`` في أي مسار هو «آخر نشاط».
- إن مرّت ``REMINDER_IDLE_HOURS`` بلا نشاط، نحدد أول درس غير مجتاز في آخر
  كورس نشط للمستخدم (هو الدرس التالي الذي يجب أن يكمله).
- لا نرسل تذكيرا جديدا قبل مرور نفس المدة من آخر تذكير (``last_reminder_at``).
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.learning import STATUS_PASSED, get_progress, ordered_lessons
from core.models import Lesson, Progress, Stage, User


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    """يوحّد المناطق الزمنية (SQLite يعيد القيم بلا tzinfo)."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value


async def latest_progress(session: AsyncSession, user_id: int) -> Progress | None:
    """آخر صف تقدّم نشط للمستخدم (أحدث ``updated_at``)."""
    res = await session.execute(
        select(Progress)
        .where(Progress.user_id == user_id)
        .order_by(Progress.updated_at.desc(), Progress.id.desc())
        .limit(1)
    )
    return res.scalar_one_or_none()


async def current_lesson(
    session: AsyncSession, user_id: int
) -> tuple[Lesson | None, int | None]:
    """الدرس الذي يجب أن يكمله المستخدم الآن، ومعرّف كورسه.

    نمرّ على المسارات من الأحدث نشاطا إلى الأقدم، ونتجاهل المسار المكتمل
    تماما — كي يجد المستخدم دائما درسا متبقيا حتى لو أنهى كورسا سابقا.
    """
    res = await session.execute(
        select(Progress)
        .where(Progress.user_id == user_id)
        .order_by(Progress.updated_at.desc(), Progress.id.desc())
    )
    seen_courses: set[int] = set()
    for prog in res.scalars().all():
        lesson = await session.get(Lesson, prog.lesson_id)
        if not lesson:
            continue
        stage = await session.get(Stage, lesson.stage_id)
        if not stage or stage.course_id in seen_courses:
            continue
        seen_courses.add(stage.course_id)
        for lsn in await ordered_lessons(session, stage.course_id):
            p = await get_progress(session, user_id, lsn.id)
            if not p or p.status != STATUS_PASSED:
                return lsn, stage.course_id
    return None, None


async def pending_reminders(
    session: AsyncSession,
    *,
    now: dt.datetime | None = None,
    idle_hours: int | None = None,
) -> list[dict]:
    """قائمة المستخدمين المستحقين لتذكير الآن.

    كل عنصر: ``{"user": User, "lesson": Lesson, "course_id": int, "idle_hours": int}``
    """
    now = _aware(now) or dt.datetime.now(dt.timezone.utc)
    hours = (
        int(settings.REMINDER_IDLE_HOURS)
        if idle_hours is None
        else max(1, int(idle_hours))
    )
    cutoff = now - dt.timedelta(hours=hours)

    res = await session.execute(
        select(User).where(User.telegram_id.is_not(None), User.is_active.is_(True))
    )
    users = list(res.scalars().all())

    due: list[dict] = []
    for user in users:
        last_reminder = _aware(user.last_reminder_at)
        if last_reminder and last_reminder > cutoff:
            continue
        prog = await latest_progress(session, user.id)
        if not prog:
            continue
        activity = _aware(prog.updated_at or prog.started_at)
        if activity and activity > cutoff:
            continue
        lesson, course_id = await current_lesson(session, user.id)
        if not lesson or course_id is None:
            continue
        due.append(
            {
                "user": user,
                "lesson": lesson,
                "course_id": course_id,
                "idle_hours": hours,
            }
        )
    return due


async def mark_reminded(
    session: AsyncSession, user_id: int, *, now: dt.datetime | None = None
) -> None:
    """يسجّل أن تذكيرا أُرسل للمستخدم الآن."""
    user = await session.get(User, user_id)
    if not user:
        return
    user.last_reminder_at = _aware(now) or dt.datetime.now(dt.timezone.utc)
    await session.commit()
