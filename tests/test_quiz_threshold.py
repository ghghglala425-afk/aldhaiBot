# -*- coding: utf-8 -*-
"""عتبة النجاح: 50% تكفي لفتح الدرس التالي، وأقل منها لا يفتح."""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from core.db import SessionLocal, engine, init_db
from core.learning import STATUS_PASSED, get_progress, is_unlocked, submit_quiz
from core.models import (
    Base,
    Course,
    Lesson,
    Option,
    Question,
    Quiz,
    Stage,
    User,
)


def _reset_db() -> None:
    async def _drop() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    asyncio.run(_drop())
    asyncio.run(init_db())


def _seed() -> tuple[int, int, list[tuple[int, int, int]]]:
    """(user_id, lesson_id, [(question_id, correct_option_id, wrong_option_id)])."""

    async def _go():
        async with SessionLocal() as s:
            user = User(username="half", email="half@t.t", telegram_id=555077)
            s.add(user)
            await s.flush()
            course = Course(
                slug="half-c", title="كورس", title_en="C", description="d",
                track="security", difficulty="beginner", icon="📘",
                order_index=1, is_published=True,
            )
            s.add(course)
            await s.flush()
            stage = Stage(
                course_id=course.id, slug="half-s", title="مرحلة",
                order_index=1, is_published=True,
            )
            s.add(stage)
            await s.flush()
            lesson = Lesson(
                stage_id=stage.id, slug="half-l", title="درس",
                summary="ملخص", objectives=["أ"], content_md="ن" * 260,
                language_slug="python", difficulty="beginner", est_minutes=20,
                order_index=1, xp_reward=50, min_score=70, status="published",
            )
            nxt = Lesson(
                stage_id=stage.id, slug="half-l2", title="التالي",
                summary="ملخص", objectives=["أ"], content_md="ن" * 260,
                language_slug="python", difficulty="beginner", est_minutes=20,
                order_index=2, xp_reward=50, min_score=70, status="published",
            )
            s.add_all([lesson, nxt])
            await s.flush()
            quiz = Quiz(lesson_id=lesson.id)
            s.add(quiz)
            await s.flush()
            pairs = []
            for i in range(2):
                q = Question(
                    quiz_id=quiz.id, text=f"س{i}", kind="single", points=1,
                    order_index=i + 1, explanation="تعليل",
                )
                s.add(q)
                await s.flush()
                good = Option(question_id=q.id, text="صح", is_correct=True, order_index=1)
                bad = Option(question_id=q.id, text="خطأ", is_correct=False, order_index=2)
                s.add_all([good, bad])
                await s.flush()
                pairs.append((q.id, good.id, bad.id))
            await s.commit()
            return user.id, lesson.id, pairs

    return asyncio.run(_go())


def _submit(uid: int, lesson_id: int, answers: dict[int, list[int]]) -> dict:
    async def _go() -> dict:
        async with SessionLocal() as s:
            user = await s.get(User, uid)
            lesson = await s.get(Lesson, lesson_id)
            return await submit_quiz(s, user, lesson, answers)

    return asyncio.run(_go())


def test_half_correct_passes_and_unlocks_next() -> None:
    _reset_db()
    try:
        uid, lesson_id, pairs = _seed()
        # نصف الإجابات صحيحة فقط (1 من 2) = 50%.
        answers = {pairs[0][0]: [pairs[0][1]], pairs[1][0]: [pairs[1][2]]}

        async def _go() -> dict:
            async with SessionLocal() as s:
                user = await s.get(User, uid)
                lesson = await s.get(Lesson, lesson_id)
                nxt = await s.scalar(select(Lesson).where(Lesson.slug == "half-l2"))
                assert not await is_unlocked(s, user, nxt), "الدرس التالي مفتوح قبل النجاح"
                result = await submit_quiz(s, user, lesson, answers)
                prog = await get_progress(s, uid, lesson_id)
                assert prog is not None and prog.status == STATUS_PASSED
                assert await is_unlocked(s, user, nxt), "الدرس التالي لم يُفتح بعد النجاح"
                return result

        result = asyncio.run(_go())
        assert result["ok"] and result["passed"], result
        assert result["score"] == 50
        assert result["threshold"] == 50
    finally:
        _reset_db()


def test_below_half_fails() -> None:
    _reset_db()
    try:
        _uid, lesson_id, pairs = _seed()
        # كل الإجابات خاطئة = 0% < 50% ⇒ لا اجتياز.
        answers = {p[0]: [p[2]] for p in pairs}
        result = _submit(_uid, lesson_id, answers)
        assert result["ok"] and not result["passed"]
        assert result["score"] == 0
        assert result["threshold"] == 50

        async def _locked() -> bool:
            async with SessionLocal() as s:
                user = await s.get(User, _uid)
                nxt = await s.scalar(select(Lesson).where(Lesson.slug == "half-l2"))
                return await is_unlocked(s, user, nxt)

        assert asyncio.run(_locked()) is False, "الدرس التالي انفتح رغم الرسوب"
    finally:
        _reset_db()
