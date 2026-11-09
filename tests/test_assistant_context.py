# -*- coding: utf-8 -*-
"""المساعد السياقي: سؤال عن درس يحمل عنوان الدرس ومحتواه في الطلب."""
from __future__ import annotations

import asyncio

from core.db import SessionLocal, engine, init_db
from core.models import Base, Course, Lesson, Stage


def _reset_db() -> None:
    async def _drop() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    asyncio.run(_drop())
    asyncio.run(init_db())


def test_context_prompt_includes_lesson_and_question() -> None:
    _reset_db()
    try:
        async def _go() -> str:
            async with SessionLocal() as s:
                course = Course(
                    slug="ctx-c", title="كورس", order_index=1, is_published=True
                )
                s.add(course)
                await s.flush()
                stage = Stage(
                    course_id=course.id, slug="ctx-s", title="مرحلة",
                    order_index=1, is_published=True,
                )
                s.add(stage)
                await s.flush()
                lesson = Lesson(
                    stage_id=stage.id, slug="ctx-l", title="درس الشبكات",
                    summary="ملخص الشبكات", objectives=["هدف"],
                    content_md="محتوى تعليمي عن HTTP", order_index=1,
                    status="published",
                )
                s.add(lesson)
                await s.commit()

                from app.handlers.assistant import _context_prompt

                return await _context_prompt(s, lesson.id, "ما هو HTTP؟")

        prompt = asyncio.run(_go())
        assert "ما هو HTTP؟" in prompt
        assert "درس الشبكات" in prompt
        assert "محتوى تعليمي عن HTTP" in prompt
        assert "ملخص الشبكات" in prompt
    finally:
        _reset_db()
