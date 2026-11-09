# -*- coding: utf-8 -*-
"""سلامة محتوى الدرس التجريبي وإصلاحه التلقائي."""
from __future__ import annotations

import asyncio
import re

from sqlalchemy import select


def test_demo_content_is_substantial_and_clean() -> None:
    from pipeline.seed import DEMO_LESSON_CONTENT as c

    assert len(c.strip()) >= 400, len(c)
    assert c.count("```") % 2 == 0, "أسوار الكود يجب أن تكون مغلقة"
    assert not re.search(r"(?i)\b(TODO|FIXME|placeholder|lorem ipsum)\b", c)
    for section in ("## نظرة عامة", "## ماذا ستتعلم", "## تمرين", "## خلاصة"):
        assert section in c, section


def test_repair_demo_lesson_updates_short_content() -> None:
    from core.db import engine, init_db
    from core.models import Base, Course, Lesson, Stage

    async def _reset() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    async def _seed_short() -> int:
        from core.db import SessionLocal

        async with SessionLocal() as s:
            course = Course(
                slug="python-security", title="بايثون للأمن", order_index=1,
                is_published=True,
            )
            s.add(course)
            await s.flush()
            stage = Stage(
                course_id=course.id, slug="basics", title="الأساسيات",
                order_index=1, is_published=True,
            )
            s.add(stage)
            await s.flush()
            lesson = Lesson(
                stage_id=stage.id, slug="hello-security", title="مرحبا",
                summary="م", objectives=["أ"], content_md="## نظرة عامة\nقصير.",
                order_index=1, status="published",
            )
            s.add(lesson)
            await s.commit()
            return lesson.id

    async def _content(lesson_id: int) -> str:
        from core.db import SessionLocal

        async with SessionLocal() as s:
            row = await s.scalar(select(Lesson).where(Lesson.id == lesson_id))
            return row.content_md or ""

    asyncio.run(_reset())
    try:
        asyncio.run(init_db())
        lesson_id = asyncio.run(_seed_short())

        from pipeline.seed import repair_demo_lesson

        assert asyncio.run(repair_demo_lesson()) is True
        content = asyncio.run(_content(lesson_id))
        assert len(content.strip()) >= 400

        # إعادة التشغيل لا تغيّر شيئا
        assert asyncio.run(repair_demo_lesson()) is False
    finally:
        asyncio.run(_reset())
