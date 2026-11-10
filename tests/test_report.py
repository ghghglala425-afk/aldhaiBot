# -*- coding: utf-8 -*-
"""التقرير الأسبوعي: يجمع الأرقام ويعرضها بلا تجاوز حد تلجرام."""
from __future__ import annotations

import asyncio
import datetime as dt
import uuid

from sqlalchemy import delete, select

from core.db import SessionLocal, init_db
from core.models import (
    AIUsage,
    Attempt,
    CodeExecution,
    Course,
    Language,
    Lesson,
    Progress,
    Quiz,
    Stage,
    User,
)
from pipeline.report import build_weekly_report, render_report


def _slug() -> str:
    return f"rep-{uuid.uuid4().int % 10**10}"


class _Seed:
    def __init__(self) -> None:
        self.lang = _slug()
        self.provider = f"test:{self.lang}"
        self.user_id: int | None = None
        self.lesson_id: int | None = None
        self.course_id: int | None = None
        self.stage_id: int | None = None

    async def create(self) -> None:
        await init_db()
        now = dt.datetime.now(dt.timezone.utc)
        async with SessionLocal() as s:
            s.add(Language(slug=self.lang, name="Report Test"))
            course = Course(slug=f"{self.lang}-mastery", title="Report Test")
            s.add(course)
            await s.flush()
            self.course_id = course.id
            stage = Stage(course_id=course.id, slug="s1", title="Stage")
            s.add(stage)
            await s.flush()
            self.stage_id = stage.id
            lesson = Lesson(
                stage_id=stage.id, slug="l1", title="Lesson", status="published"
            )
            s.add(lesson)
            await s.flush()
            self.lesson_id = lesson.id
            quiz = Quiz(lesson_id=lesson.id)
            s.add(quiz)
            user = User(
                telegram_id=980_000_000 + uuid.uuid4().int % 1_000_000,
                username=f"rp{uuid.uuid4().hex[:10]}",
                created_at=now,
                last_seen=now,
            )
            s.add(user)
            await s.flush()
            self.user_id = user.id
            await s.flush()
            s.add(
                Progress(
                    user_id=user.id,
                    lesson_id=lesson.id,
                    status="passed",
                    best_score=90,
                    completed_at=now,
                )
            )
            s.add(
                Attempt(
                    user_id=user.id,
                    quiz_id=quiz.id,
                    lesson_id=lesson.id,
                    score=90,
                    passed=True,
                    started_at=now,
                )
            )
            s.add(
                AIUsage(
                    provider=self.provider,
                    day=now.date(),
                    requests=4,
                    tokens=5000,
                    errors=1,
                )
            )
            s.add(
                CodeExecution(
                    user_id=user.id,
                    lesson_id=lesson.id,
                    language="python",
                    status="ok",
                    execution_time_ms=120,
                )
            )
            await s.commit()

    async def cleanup(self) -> None:
        async with SessionLocal() as s:
            await s.execute(
                delete(AIUsage).where(AIUsage.provider == self.provider)
            )
            if self.user_id:
                await s.execute(
                    delete(CodeExecution).where(CodeExecution.user_id == self.user_id)
                )
                await s.execute(delete(Attempt).where(Attempt.user_id == self.user_id))
                await s.execute(
                    delete(Progress).where(Progress.user_id == self.user_id)
                )
                await s.execute(delete(User).where(User.id == self.user_id))
            if self.lesson_id:
                await s.execute(delete(Quiz).where(Quiz.lesson_id == self.lesson_id))
                await s.execute(delete(Lesson).where(Lesson.id == self.lesson_id))
            if self.stage_id:
                await s.execute(delete(Stage).where(Stage.id == self.stage_id))
            if self.course_id:
                await s.execute(delete(Course).where(Course.id == self.course_id))
            await s.execute(delete(Language).where(Language.slug == self.lang))
            await s.commit()


class TestWeeklyReport:
    def test_collects_numbers(self) -> None:
        seed = _Seed()

        async def _go() -> dict:
            await seed.create()
            return await build_weekly_report()

        try:
            data = asyncio.run(_go())
        finally:
            asyncio.run(seed.cleanup())

        assert data["users"]["total"] >= 1
        assert data["users"]["new"] >= 1
        assert data["users"]["active"] >= 1
        assert data["learning"]["completed"] >= 1
        assert data["learning"]["attempts"] >= 1
        assert data["learning"]["passed"] >= 1
        assert data["learning"]["published"] >= 1
        assert data["code"]["runs"] >= 1
        assert data["code"]["ok"] >= 1
        assert data["code"]["avg_ms"] >= 100
        assert data["ai"]["requests"] >= 4
        assert data["ai"]["tokens"] >= 5000
        assert any(p["id"] == seed.provider for p in data["ai"]["paths"])
        assert "queued" in data["queue"]

    def test_render_is_telegram_safe(self) -> None:
        seed = _Seed()

        async def _go() -> str:
            await seed.create()
            return render_report(await build_weekly_report())

        try:
            text = asyncio.run(_go())
        finally:
            asyncio.run(seed.cleanup())

        assert "التقرير الأسبوعي" in text
        assert "المستخدمون" in text
        assert "التعلّم" in text
        assert "الذكاء الاصطناعي" in text
        assert "تشغيل الكود" in text
        assert "طابور التوليد" in text
        assert len(text) <= 4000, "يجب ألا تتجاوز رسالة تلجرام"

    def test_render_empty_period(self) -> None:
        text = render_report(
            {
                "from": dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
                "to": dt.datetime(2026, 1, 8, tzinfo=dt.timezone.utc),
                "days": 7,
                "users": {"total": 0, "new": 0, "active": 0},
                "learning": {
                    "completed": 0,
                    "attempts": 0,
                    "passed": 0,
                    "published": 0,
                    "outline": 0,
                },
                "code": {"runs": 0, "ok": 0, "avg_ms": 0.0, "top_languages": []},
                "ai": {"paths": [], "requests": 0, "tokens": 0, "errors": 0},
                "queue": {"queued": 0, "running": 0, "failed": 0, "done": 0},
            }
        )
        assert "لا استهلاك مسجّل" in text
        assert "—" in text or "0%" in text
