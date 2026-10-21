# -*- coding: utf-8 -*-
"""إعادة الاختبار: لا تفقد الاجتياز ولا تمنح نقاطا مكررة."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from core.db import SessionLocal, engine, init_db
from core.learning import STATUS_PASSED, get_progress, submit_quiz
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


def _seed() -> tuple[int, int, int, int, int, int]:
    """(user_id, lesson_id, question_id, correct, wrong, next_lesson_id)."""

    async def _go() -> tuple[int, int, int, int, int, int]:
        async with SessionLocal() as s:
            user = User(username="retaker", email="r@r.r", telegram_id=555002)
            s.add(user)
            await s.flush()
            course = Course(
                slug="cr", title="كورس", title_en="C", description="d",
                track="security", difficulty="beginner", icon="📘",
                order_index=1, is_published=True,
            )
            s.add(course)
            await s.flush()
            stage = Stage(
                course_id=course.id, slug="sr", title="مرحلة",
                order_index=1, is_published=True,
            )
            s.add(stage)
            await s.flush()
            lesson = Lesson(
                stage_id=stage.id, slug="lr", title="درس",
                summary="ملخص", objectives=["أ"], content_md="ن" * 260,
                language_slug="python", difficulty="beginner", est_minutes=20,
                order_index=1, xp_reward=50, min_score=70, status="published",
            )
            s.add(lesson)
            await s.flush()
            following = Lesson(
                stage_id=stage.id, slug="lr2", title="الدرس التالي",
                summary="ملخص", objectives=["أ"], content_md="ن" * 260,
                language_slug="python", difficulty="beginner", est_minutes=20,
                order_index=2, xp_reward=50, min_score=70, status="published",
            )
            s.add(following)
            await s.flush()
            quiz = Quiz(lesson_id=lesson.id)
            s.add(quiz)
            await s.flush()
            q = Question(quiz_id=quiz.id, text="س؟", kind="single", points=1, order_index=1)
            s.add(q)
            await s.flush()
            good = Option(question_id=q.id, text="صح", is_correct=True, order_index=1)
            bad = Option(question_id=q.id, text="خطأ", is_correct=False, order_index=2)
            s.add_all([good, bad])
            await s.commit()
            return user.id, lesson.id, q.id, good.id, bad.id, following.id

    return asyncio.run(_go())


def test_result_keyboard_has_next_retake_and_exercise() -> None:
    from app.handlers.learn import _quiz_done_kb

    kb = _quiz_done_kb(7, 8, passed=True)
    datas = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "lesson:8" in datas
    assert "qz_start:7" in datas
    assert "exs:7" in datas

    failed = _quiz_done_kb(7, 8, passed=False)
    failed_datas = [b.callback_data for row in failed.inline_keyboard for b in row]
    assert "lesson:8" not in failed_datas
    assert "qz_start:7" in failed_datas


def test_retake_after_pass_keeps_passed_and_does_not_duplicate_xp() -> None:
    _reset_db()
    try:
        user_id, lesson_id, qid, good, bad, _next_id = _seed()

        async def _go() -> tuple[int, bool, int]:
            async with SessionLocal() as s:
                user = await s.get(User, user_id)
                lesson = await s.get(Lesson, lesson_id)
                first = await submit_quiz(s, user, lesson, {qid: [good]})
                assert first["passed"] and first["xp"] == 50
                xp_after_first = user.xp

                # إعادة ناجحة: لا نقاط إضافية.
                again = await submit_quiz(s, user, lesson, {qid: [good]})
                assert again["passed"] and again["xp"] == 0
                assert user.xp == xp_after_first

                # إعادة فاشلة: يبقى الدرس مجتازا.
                fail = await submit_quiz(s, user, lesson, {qid: [bad]})
                assert not fail["passed"]
                prog = await get_progress(s, user_id, lesson_id)
                return user.xp, prog.status == STATUS_PASSED, prog.attempts_count

        xp, still_passed, attempts = asyncio.run(_go())
        assert xp == 50
        assert still_passed is True
        assert attempts == 3
    finally:
        _reset_db()


def test_after_quiz_pass_opens_next_lesson(monkeypatch) -> None:
    _reset_db()
    try:
        user_id, lesson_id, qid, good, _bad, next_id = _seed()
        calls: list[tuple[int, dict]] = []

        async def _fake_display(bot, chat_id, lid, **kw):
            calls.append((lid, kw))

        import app.handlers.learn as learn

        monkeypatch.setattr(learn, "_display_and_build", _fake_display)

        async def _go() -> None:
            async with SessionLocal() as s:
                user = await s.get(User, user_id)
                lesson = await s.get(Lesson, lesson_id)
                await submit_quiz(s, user, lesson, {qid: [good]})
                update = SimpleNamespace(
                    effective_chat=SimpleNamespace(id=999),
                    effective_user=SimpleNamespace(id=555002),
                    effective_message=None,
                )
                context = SimpleNamespace(bot=object())
                await learn._after_quiz_pass(update, context, lesson)

        asyncio.run(_go())
        assert calls, "must open the next lesson after passing"
        assert calls[0][0] == next_id
        assert "الدرس التالي" in calls[0][1].get("notice", "")
    finally:
        _reset_db()

