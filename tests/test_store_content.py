# -*- coding: utf-8 -*-
"""حفظ الدرس وإعادة توليده: استبدال الاختبار بلا أخطاء NotNull/FK."""
from __future__ import annotations

import asyncio

from core.db import SessionLocal, engine, init_db
from core.models import Base, Option, Question, Quiz
from pipeline.schema import (
    GeneratedCode,
    GeneratedLesson,
    GeneratedOption,
    GeneratedQuestion,
)
from pipeline.store_content import save_lesson
from pipeline.taxonomy import LessonPlan
from sqlalchemy import func, select


def _reset_db() -> None:
    async def _drop() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    asyncio.run(_drop())
    asyncio.run(init_db())


def _plan() -> LessonPlan:
    return LessonPlan(
        course_slug="c1",
        course_title="كورس",
        icon="📘",
        language="python",
        stage="الأساسيات",
        stage_index=1,
        topic="المتغيرات",
        lesson_index=1,
        difficulty="beginner",
    )


def _lesson(title: str) -> GeneratedLesson:
    return GeneratedLesson(
        title=title,
        summary="ملخص كافٍ للدرس التجريبي.",
        objectives=["هدف أول", "هدف ثان"],
        content_md="ن" * 260,
        difficulty="beginner",
        est_minutes=20,
        code_samples=[
            GeneratedCode(
                language="python",
                title="مثال",
                code="print(1)",
                explanation="يطبع رقما.",
            )
        ],
        quiz_questions=[
            GeneratedQuestion(
                text="ما ناتج الطباعة؟",
                kind="single",
                options=[
                    GeneratedOption(text="1", correct=True),
                    GeneratedOption(text="2", correct=False),
                ],
                explanation="لأننا طبعنا الرقم 1.",
            )
        ],
    )


def test_regenerating_lesson_replaces_quiz_cleanly() -> None:
    _reset_db()
    try:
        async def _go() -> tuple[int, int, int]:
            async with SessionLocal() as s:
                await save_lesson(s, _plan(), _lesson("الدرس الأول"), verified=True, publish=True)
            # إعادة التوليد في جلسة جديدة: يجب أن تحذف الأسئلة والخيارات القديمة.
            async with SessionLocal() as s:
                await save_lesson(s, _plan(), _lesson("الدرس الأول"), verified=True, publish=True)
                q_count = int(
                    await s.scalar(
                        select(func.count()).select_from(Question)
                    )
                    or 0
                )
                o_count = int(
                    await s.scalar(select(func.count()).select_from(Option)) or 0
                )
                quiz = await s.scalar(select(Quiz))
                o_null = int(
                    await s.scalar(
                        select(func.count())
                        .select_from(Option)
                        .where(Option.question_id.is_(None))
                    )
                    or 0
                )
                assert quiz is not None
                return q_count, o_count, o_null

        questions, options, nulls = asyncio.run(_go())
        assert (questions, options, nulls) == (1, 2, 0)
    finally:
        _reset_db()
