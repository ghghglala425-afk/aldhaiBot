# -*- coding: utf-8 -*-
"""التسخين المسبق لأشهر اللغات: أول N درس فقط، وبلا تكرار."""
from __future__ import annotations

import asyncio
import uuid
from unittest.mock import patch

from sqlalchemy import delete, select

from core.config import settings
from core.db import SessionLocal, init_db
from core.models import Course, GenerationJob, Language, Lesson, Stage
from pipeline import jobs


def _slug() -> str:
    return f"warm-{uuid.uuid4().int % 10**10}"


async def _seed(lang: str, *, total: int = 8, published_first: bool = False) -> list[int]:
    await init_db()
    async with SessionLocal() as s:
        s.add(Language(slug=lang, name="Warm Test"))
        course = Course(slug=f"{lang}-mastery", title="Warm Test")
        s.add(course)
        await s.flush()
        stage = Stage(course_id=course.id, slug="s1", title="Stage", order_index=1)
        s.add(stage)
        await s.flush()
        ids: list[int] = []
        for i in range(1, total + 1):
            status = "published" if (published_first and i == 1) else "outline"
            lesson = Lesson(
                stage_id=stage.id,
                slug=f"l{i}",
                title=f"Lesson {i}",
                order_index=i,
                status=status,
            )
            s.add(lesson)
            await s.flush()
            ids.append(lesson.id)
        await s.commit()
        return ids


async def _cleanup(lang: str, ids: list[int]) -> None:
    async with SessionLocal() as s:
        await s.execute(
            delete(GenerationJob).where(
                (GenerationJob.language == lang)
                | (GenerationJob.lesson_id.in_(ids or [0]))
            )
        )
        await s.execute(delete(Lesson).where(Lesson.id.in_(ids or [0])))
        courses = list(
            (await s.execute(select(Course).where(Course.slug == f"{lang}-mastery")))
            .scalars()
        )
        for course in courses:
            stages = list(
                (await s.execute(select(Stage).where(Stage.course_id == course.id)))
                .scalars()
            )
            if stages:
                await s.execute(delete(Stage).where(Stage.id.in_([st.id for st in stages])))
            await s.execute(delete(Course).where(Course.id == course.id))
        await s.execute(delete(Language).where(Language.slug == lang))
        await s.commit()


async def _queued_lesson_ids(lang: str) -> list[int]:
    async with SessionLocal() as s:
        rows = (
            await s.execute(
                select(GenerationJob.lesson_id)
                .where(
                    GenerationJob.kind == "lesson",
                    GenerationJob.status.in_(("queued", "running")),
                    GenerationJob.lesson_id.is_not(None),
                )
                .order_by(GenerationJob.lesson_id)
            )
        ).scalars()
        return [x for x in rows if x is not None]


class TestWarmFront:
    def test_queues_only_first_n(self) -> None:
        lang = _slug()

        async def _go() -> None:
            ids = await _seed(lang, total=8)
            try:
                with patch.object(settings, "GEN_QUEUE_MAX", 0):
                    result = await jobs.warm_popular(languages=[lang], lessons=3)
                    assert result == {lang: 3}
                    queued = await _queued_lesson_ids(lang)
                    assert queued == ids[:3], "يجب ألا يتجاوز أول 3 دروس"
            finally:
                await _cleanup(lang, ids)

        asyncio.run(_go())

    def test_is_idempotent(self) -> None:
        lang = _slug()

        async def _go() -> None:
            ids = await _seed(lang, total=6)
            try:
                with patch.object(settings, "GEN_QUEUE_MAX", 0):
                    assert await jobs.warm_popular(languages=[lang], lessons=3) == {lang: 3}
                    again = await jobs.warm_popular(languages=[lang], lessons=3)
                    assert again == {lang: 0}, "الاستدعاء الثاني يجب ألا يكرّر المهام"
            finally:
                await _cleanup(lang, ids)

        asyncio.run(_go())

    def test_skips_published_and_does_not_advance_past_n(self) -> None:
        lang = _slug()

        async def _go() -> None:
            ids = await _seed(lang, total=8, published_first=True)
            try:
                with patch.object(settings, "GEN_QUEUE_MAX", 0):
                    async with SessionLocal() as s:
                        added = await jobs.enqueue_warm_front(s, lang, 3)
                    assert added == 2, "الدرس المنشور لا يُدرج"
                    queued = await _queued_lesson_ids(lang)
                    assert queued == ids[1:3]
                    assert ids[3] not in queued, "لا يتقدّم إلى الدرس الرابع"
            finally:
                await _cleanup(lang, ids)

        asyncio.run(_go())

    def test_zero_lessons_is_noop(self) -> None:
        lang = _slug()

        async def _go() -> None:
            ids = await _seed(lang, total=4)
            try:
                with patch.object(settings, "GEN_QUEUE_MAX", 0):
                    async with SessionLocal() as s:
                        assert await jobs.enqueue_warm_front(s, lang, 0) == 0
                    assert await _queued_lesson_ids(lang) == []
            finally:
                await _cleanup(lang, ids)

        asyncio.run(_go())

    def test_missing_outline_enqueues_outline_only(self) -> None:
        lang = _slug()

        async def _go() -> None:
            await init_db()
            async with SessionLocal() as s:
                s.add(Language(slug=lang, name="No Outline"))
                await s.commit()
            try:
                with patch.object(settings, "GEN_QUEUE_MAX", 0):
                    result = await jobs.warm_popular(languages=[lang], lessons=3)
                    assert result == {lang: 0}
                async with SessionLocal() as s:
                    job = await s.scalar(
                        select(GenerationJob).where(
                            GenerationJob.dedup_key == f"outline:{lang}"
                        )
                    )
                assert job is not None and job.kind == "outline"
            finally:
                await _cleanup(lang, [])

        asyncio.run(_go())


class TestStartupWarm:
    def test_disabled_returns_none(self) -> None:
        with patch.object(settings, "PREBUILD_ENABLED", False):
            assert jobs.start_initial_warm() is None
