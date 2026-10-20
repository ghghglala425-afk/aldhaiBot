# -*- coding: utf-8 -*-
"""اختبارات تسجيل بدء التعلّم وكشف سقوط قاعدة البيانات."""
from __future__ import annotations

import asyncio

from sqlalchemy import func, select

from core.db import SessionLocal, engine, init_db
from core.learning import (
    STATUS_IN_PROGRESS,
    STATUS_LOCKED,
    STATUS_PASSED,
    get_progress,
    start_lesson,
    status_map,
)
from core.models import Course, Lesson, Progress, Stage, User


def _reset_db() -> None:
    from core.models import Base

    async def _drop() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    asyncio.run(_drop())
    asyncio.run(init_db())


def _seed_course_and_lesson() -> tuple[int, int, int]:
    """ينشئ مستخدما وكورسا وثلاثة دروس. يعيد (user_id, course_id, lesson_id)."""

    async def _go() -> tuple[int, int, int]:
        async with SessionLocal() as s:
            user = User(username="learner", email="l@l.l", telegram_id=555001)
            s.add(user)
            await s.flush()
            course = Course(
                slug="c1", title="كورس", title_en="C", description="d",
                track="security", difficulty="beginner", icon="📘",
                order_index=1, is_published=True,
            )
            s.add(course)
            await s.flush()
            stage = Stage(course_id=course.id, slug="s1", title="م��", order_index=1, is_published=True)
            s.add(stage)
            await s.flush()
            ids = []
            for i in range(1, 4):
                lesson = Lesson(
                    stage_id=stage.id, slug=f"l{i}", title=f"درس {i}",
                    summary="ملخص", objectives=["أ"], content_md="ن"*260,
                    language_slug="python", difficulty="beginner", est_minutes=20,
                    order_index=i, xp_reward=50, min_score=70, status="published",
                )
                s.add(lesson)
                await s.flush()
                ids.append(lesson.id)
            await s.commit()
            return user.id, course.id, ids[0]

    return asyncio.run(_go())


class TestStartLesson:
    """فتح الدرس يجب أن يكتب في قاعدة البيانات."""

    def test_start_lesson_creates_progress_row(self) -> None:
        _reset_db()
        try:
            user_id, _course_id, lesson_id = _seed_course_and_lesson()

            async def _go() -> Progress:
                async with SessionLocal() as s:
                    return await start_lesson(s, user_id, lesson_id)

            prog = asyncio.run(_go())
            assert prog.id is not None, "a progress row must be created"
            assert prog.status == STATUS_IN_PROGRESS
            assert prog.started_at is not None, "started_at must be set"
        finally:
            _reset_db()

    def test_start_lesson_is_idempotent(self) -> None:
        _reset_db()
        try:
            user_id, _course_id, lesson_id = _seed_course_and_lesson()

            async def _go() -> tuple[Progress, Progress]:
                async with SessionLocal() as s:
                    first = await start_lesson(s, user_id, lesson_id)
                    second = await start_lesson(s, user_id, lesson_id)
                    return first, second

            first, second = asyncio.run(_go())
            assert first.id == second.id, "must not create a second row"
            assert first.started_at == second.started_at, "started_at must not change"
        finally:
            _reset_db()

    def test_start_lesson_keeps_passed_status(self) -> None:
        """درس مكتمل لا يعود إلى in_progress."""
        _reset_db()
        try:
            user_id, _course_id, lesson_id = _seed_course_and_lesson()

            async def _go() -> Progress:
                async with SessionLocal() as s:
                    p = await start_lesson(s, user_id, lesson_id)
                    p.status = STATUS_PASSED
                    p.completed_at = p.started_at
                    await s.commit()
                    again = await start_lesson(s, user_id, lesson_id)
                    return again

            prog = asyncio.run(_go())
            assert prog.status == STATUS_PASSED
        finally:
            _reset_db()

    def test_progress_row_is_queryable(self) -> None:
        """الصف يبقى محفوظا ويمكن الاستعلام عنه."""
        _reset_db()
        try:
            user_id, _course_id, lesson_id = _seed_course_and_lesson()

            async def _go() -> int:
                async with SessionLocal() as s:
                    await start_lesson(s, user_id, lesson_id)
                async with SessionLocal() as s:
                    n = (await s.execute(
                        select(func.count()).select_from(Progress)
                        .where(Progress.user_id == user_id)
                    )).scalar()
                    return n or 0

            assert asyncio.run(_go()) == 1
        finally:
            _reset_db()


class TestStatusMapInProgress:
    """الدرس الذي بدأه المستخدم يظهر كـ «قيد التعلّم» ويبقى التالي مقفلا."""

    def test_in_progress_lesson_is_marked(self) -> None:
        _reset_db()
        try:
            user_id, course_id, lesson_id = _seed_course_and_lesson()

            async def _go() -> list[dict]:
                async with SessionLocal() as s:
                    await start_lesson(s, user_id, lesson_id)
                async with SessionLocal() as s:
                    user = await s.get(User, user_id)
                    return await status_map(s, user, course_id)

            rows = asyncio.run(_go())
            assert rows[0]["status"] == STATUS_IN_PROGRESS
            assert rows[0]["started_at"] is not None
        finally:
            _reset_db()

    def test_next_lesson_stays_locked(self) -> None:
        """بدء الدرس الأول لا يفتح الثاني."""
        _reset_db()
        try:
            user_id, course_id, lesson_id = _seed_course_and_lesson()

            async def _go() -> list[dict]:
                async with SessionLocal() as s:
                    await start_lesson(s, user_id, lesson_id)
                async with SessionLocal() as s:
                    user = await s.get(User, user_id)
                    return await status_map(s, user, course_id)

            rows = asyncio.run(_go())
            assert rows[1]["status"] == STATUS_LOCKED, (
                "the next lesson must stay locked until the current one is passed"
            )
        finally:
            _reset_db()

    def test_passed_lesson_unlocks_the_next(self) -> None:
        _reset_db()
        try:
            user_id, course_id, lesson_id = _seed_course_and_lesson()

            async def _go() -> list[dict]:
                async with SessionLocal() as s:
                    p = await start_lesson(s, user_id, lesson_id)
                    p.status = STATUS_PASSED
                    await s.commit()
                async with SessionLocal() as s:
                    user = await s.get(User, user_id)
                    return await status_map(s, user, course_id)

            rows = asyncio.run(_go())
            assert rows[0]["status"] == STATUS_PASSED
            assert rows[1]["status"] != STATUS_LOCKED
        finally:
            _reset_db()


class TestLessonTimeTracking:
    """تسجيل مدة التعلّم."""

    def test_long_session_is_logged(self) -> None:
        import datetime as dt

        from core.learning import finish_lesson_time
        from core.models import LessonTimeLog

        _reset_db()
        try:
            user_id, _course_id, lesson_id = _seed_course_and_lesson()

            async def _go() -> int:
                async with SessionLocal() as s:
                    p = await start_lesson(s, user_id, lesson_id)
                    # جلسة مدتها 12 دقيقة
                    p.started_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=12)
                    await s.commit()
                    await finish_lesson_time(s, user_id, lesson_id)
                    n = (await s.execute(
                        select(func.count()).select_from(LessonTimeLog)
                    )).scalar()
                    return n or 0

            assert asyncio.run(_go()) == 1, "a long session must be logged"
        finally:
            _reset_db()

    def test_quick_click_is_not_logged(self) -> None:
        """نقرة عابرة لا تُسجَّل كوقت تعلّم."""
        from core.learning import finish_lesson_time
        from core.models import LessonTimeLog

        _reset_db()
        try:
            user_id, _course_id, lesson_id = _seed_course_and_lesson()

            async def _go() -> int:
                async with SessionLocal() as s:
                    await start_lesson(s, user_id, lesson_id)
                    await finish_lesson_time(s, user_id, lesson_id)
                    n = (await s.execute(
                        select(func.count()).select_from(LessonTimeLog)
                    )).scalar()
                    return n or 0

            assert asyncio.run(_go()) == 0
        finally:
            _reset_db()


class TestDbFallbackDetection:

    def test_helpers_exist(self) -> None:
        from core import db

        assert callable(db.fallback_reason)
        assert callable(db.using_sqlite)
        assert callable(db.is_misconfigured)

    def test_choose_reports_reason(self) -> None:
        from core.db import SQLITE_FALLBACK, choose_database_url

        url, reason = choose_database_url(None)
        assert url == SQLITE_FALLBACK
        assert reason == "unset"

        url, reason = choose_database_url("${{Postgres.DATABASE_URL}}")
        assert url == SQLITE_FALLBACK
        assert reason == "unresolved-reference"

    def test_valid_postgres_is_not_a_fallback(self) -> None:
        from core.db import choose_database_url

        url, reason = choose_database_url("postgresql://u:p@localhost:5432/db")
        assert url == "postgresql+asyncpg://u:p@localhost:5432/db"
        assert reason == "postgres"

    def test_diag_reports_persistence(self) -> None:
        from app.bot import _diag_database

        info = _diag_database()
        assert "kind" in info
        assert "persistent" in info
        assert "fallback_reason" in info
        assert "misconfigured" in info
