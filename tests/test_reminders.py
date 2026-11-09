# -*- coding: utf-8 -*-
"""التذكير الدراسي: يُرسل بعد 23 ساعة خمول، ولا يتكرر قبل 23 ساعة."""
from __future__ import annotations

import asyncio
import datetime as dt

from sqlalchemy import select

from core.db import SessionLocal, engine, init_db
from core.learning import STATUS_IN_PROGRESS, STATUS_PASSED
from core.models import Base, Course, Lesson, Progress, Stage, User
from core.reminders import mark_reminded, pending_reminders

NOW = dt.datetime(2026, 5, 1, 12, 0, tzinfo=dt.timezone.utc)


def _reset_db() -> None:
    async def _drop() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    asyncio.run(_drop())
    asyncio.run(init_db())


def _seed() -> tuple[int, int, int]:
    """(user_id, lesson1_id, lesson2_id) مع تقدّم خامل في الدرس الأول."""

    async def _go() -> tuple[int, int, int]:
        async with SessionLocal() as s:
            user = User(username="sleepy", email="s@s.s", telegram_id=555099)
            s.add(user)
            await s.flush()
            course = Course(
                slug="rem-c", title="كورس", title_en="C", description="d",
                track="security", difficulty="beginner", icon="📘",
                order_index=1, is_published=True,
            )
            s.add(course)
            await s.flush()
            stage = Stage(
                course_id=course.id, slug="rem-s", title="مرحلة",
                order_index=1, is_published=True,
            )
            s.add(stage)
            await s.flush()
            first = Lesson(
                stage_id=stage.id, slug="rem-l1", title="الأول",
                summary="ملخص", objectives=["أ"], content_md="ن" * 260,
                order_index=1, status="published",
            )
            second = Lesson(
                stage_id=stage.id, slug="rem-l2", title="الثاني",
                summary="ملخص", objectives=["أ"], content_md="ن" * 260,
                order_index=2, status="published",
            )
            s.add_all([first, second])
            await s.flush()
            s.add(
                Progress(
                    user_id=user.id,
                    lesson_id=first.id,
                    status=STATUS_IN_PROGRESS,
                    updated_at=NOW - dt.timedelta(hours=24),
                )
            )
            await s.commit()
            return user.id, first.id, second.id

    return asyncio.run(_go())


def _pending(uid: int) -> list[dict]:
    async def _go() -> list[dict]:
        async with SessionLocal() as s:
            return await pending_reminders(s, now=NOW, idle_hours=23)

    return asyncio.run(_go())


def test_idle_user_gets_reminder_for_current_lesson() -> None:
    _reset_db()
    try:
        _uid, lesson1, _lesson2 = _seed()
        due = _pending(_uid)
        assert len(due) == 1
        assert due[0]["lesson"].id == lesson1
        assert due[0]["user"].telegram_id == 555099
    finally:
        _reset_db()


def test_recent_activity_skips_reminder() -> None:
    _reset_db()
    try:
        uid, lesson1, _lesson2 = _seed()

        async def _touch() -> None:
            async with SessionLocal() as s:
                row = await s.scalar(
                    select(Progress).where(Progress.user_id == uid)
                )
                row.updated_at = NOW - dt.timedelta(hours=2)
                row.lesson_id = lesson1
                await s.commit()

        asyncio.run(_touch())
        assert _pending(uid) == []
    finally:
        _reset_db()


def test_reminder_not_repeated_before_23_hours() -> None:
    _reset_db()
    try:
        uid, _lesson1, _lesson2 = _seed()

        async def _mark() -> None:
            async with SessionLocal() as s:
                await mark_reminded(s, uid, now=NOW)

        asyncio.run(_mark())
        assert _pending(uid) == []
    finally:
        _reset_db()


def test_completed_course_has_no_reminder() -> None:
    _reset_db()
    try:
        uid, lesson1, lesson2 = _seed()

        async def _finish() -> None:
            async with SessionLocal() as s:
                row = await s.scalar(
                    select(Progress).where(Progress.user_id == uid)
                )
                row.status = STATUS_PASSED
                s.add(
                    Progress(
                        user_id=uid,
                        lesson_id=lesson2,
                        status=STATUS_PASSED,
                        updated_at=NOW - dt.timedelta(hours=24),
                    )
                )
                await s.commit()

        asyncio.run(_finish())
        assert _pending(uid) == []
    finally:
        _reset_db()
