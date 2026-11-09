# -*- coding: utf-8 -*-
"""الدرس اليومي للمسار المختار: الترتيب، عدم تجاوز الدرس قيد التقدّم، والعدّ اليومي."""
from __future__ import annotations

import asyncio
import datetime as dt

from sqlalchemy import select

from core.db import SessionLocal, engine, init_db
from core.learning import (
    STATUS_IN_PROGRESS,
    STATUS_PASSED,
    next_study_lesson,
    passed_today,
    selected_courses,
    todays_daily,
)
from core.models import (
    Base,
    Course,
    LearningPath,
    Lesson,
    Progress,
    Stage,
    User,
)


def _reset_db() -> None:
    async def _drop() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    asyncio.run(_drop())
    asyncio.run(init_db())


def _seed() -> dict:
    async def _go() -> dict:
        async with SessionLocal() as s:
            user = User(username="tracker", email="t@t.t", telegram_id=555111)
            s.add(user)
            await s.flush()

            def _course(slug: str, order: int) -> Course:
                c = Course(
                    slug=slug, title=slug, title_en=slug, description="d",
                    track="security", difficulty="beginner", icon="📘",
                    order_index=order, is_published=True,
                )
                s.add(c)
                return c

            a = _course("course-a", 1)
            b = _course("course-b", 2)
            await s.flush()

            def _stage(course: Course) -> Stage:
                st = Stage(
                    course_id=course.id, slug=f"{course.slug}-s", title="مرحلة",
                    order_index=1, is_published=True,
                )
                s.add(st)
                return st

            sa, sb = _stage(a), _stage(b)
            await s.flush()

            def _lesson(stage: Stage, slug: str, order: int) -> Lesson:
                ls = Lesson(
                    stage_id=stage.id, slug=slug, title=slug, summary="م",
                    objectives=["أ"], content_md="ن" * 260, order_index=order,
                    status="published",
                )
                s.add(ls)
                return ls

            a1 = _lesson(sa, "a1", 1)
            a2 = _lesson(sa, "a2", 2)
            b1 = _lesson(sb, "b1", 1)
            await s.flush()

            s.add(
                LearningPath(
                    slug="track", title="المسار", description="د",
                    icon="🛤️", order=1, course_slugs=["course-a", "course-b"],
                )
            )
            s.add(
                Progress(
                    user_id=user.id, lesson_id=a1.id, status=STATUS_PASSED,
                    completed_at=dt.datetime.now(dt.timezone.utc),
                    updated_at=dt.datetime.now(dt.timezone.utc),
                )
            )
            user.active_path_slug = "track"
            await s.commit()
            return {
                "uid": user.id,
                "a": a.id,
                "b": b.id,
                "a1": a1.id,
                "a2": a2.id,
                "b1": b1.id,
            }

    return asyncio.run(_go())


def test_selected_courses_follows_path_order() -> None:
    _reset_db()
    try:
        ids = _seed()

        async def _go() -> list[int]:
            async with SessionLocal() as s:
                user = await s.get(User, ids["uid"])
                courses = await selected_courses(s, user)
                return [c.id for c in courses]

        assert asyncio.run(_go()) == [ids["a"], ids["b"]]
    finally:
        _reset_db()


def test_daily_comes_from_selected_path_not_other_course() -> None:
    _reset_db()
    try:
        ids = _seed()

        async def _go() -> int | None:
            async with SessionLocal() as s:
                user = await s.get(User, ids["uid"])
                lesson = await todays_daily(s, user)
                return lesson.id if lesson else None

        assert asyncio.run(_go()) == ids["a2"]
    finally:
        _reset_db()


def test_daily_keeps_in_progress_lesson() -> None:
    """الدرس الذي بدأه المستخدم لا يُتجاوز إلى الدرس التالي."""
    _reset_db()
    try:
        ids = _seed()

        async def _go() -> int | None:
            async with SessionLocal() as s:
                s.add(
                    Progress(
                        user_id=ids["uid"], lesson_id=ids["a2"],
                        status=STATUS_IN_PROGRESS,
                        updated_at=dt.datetime.now(dt.timezone.utc),
                    )
                )
                await s.commit()
                user = await s.get(User, ids["uid"])
                lesson = await todays_daily(s, user)
                return lesson.id if lesson else None

        assert asyncio.run(_go()) == ids["a2"]
    finally:
        _reset_db()


def test_next_study_lesson_crosses_to_next_course_in_path() -> None:
    _reset_db()
    try:
        ids = _seed()

        async def _go() -> int | None:
            async with SessionLocal() as s:
                user = await s.get(User, ids["uid"])
                # اجتياز كل دروس الكورس الأول ⇒ التالي من الكورس الثاني.
                for lid in (ids["a1"], ids["a2"]):
                    row = await s.scalar(
                        select(Progress).where(
                            Progress.user_id == user.id, Progress.lesson_id == lid
                        )
                    )
                    if row:
                        row.status = STATUS_PASSED
                    else:
                        s.add(
                            Progress(
                                user_id=user.id, lesson_id=lid, status=STATUS_PASSED
                            )
                        )
                await s.commit()
                lesson = await next_study_lesson(s, user)
                return lesson.id if lesson else None

        assert asyncio.run(_go()) == ids["b1"]
    finally:
        _reset_db()


def test_passed_today_counts_recent_passes() -> None:
    _reset_db()
    try:
        ids = _seed()

        async def _go() -> int:
            async with SessionLocal() as s:
                return await passed_today(s, ids["uid"])

        assert asyncio.run(_go()) == 1
    finally:
        _reset_db()
