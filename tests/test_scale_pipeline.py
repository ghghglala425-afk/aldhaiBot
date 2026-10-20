# -*- coding: utf-8 -*-
"""اختبارات التوسّع: مخطط اللغات (Outline) + طابور التوليد والعامل (بـAI مزيّف)."""
from __future__ import annotations

import asyncio

from sqlalchemy import func, select

from core.db import SessionLocal, engine, init_db
from core.models import Base, Course, Language, Lesson, Stage
from pipeline import jobs
from pipeline.outline import build_language_outline
from pipeline.schema import GeneratedLesson
from pipeline.taxonomy import iter_language_lessons
from pipeline.verifier import VerifyReport


async def _drop_all() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


def _reset_db() -> None:
    asyncio.run(_drop_all())
    asyncio.run(init_db())


async def _seed_python() -> None:
    async with SessionLocal() as s:
        exists = await s.scalar(select(Language).where(Language.slug == "python"))
        if not exists:
            s.add(Language(slug="python", name="Python", name_ar="بايثون",
                           paradigm="multi", difficulty="easy", docker_image="python:3.12-slim"))
            await s.commit()


def _fake_lesson() -> GeneratedLesson:
    return GeneratedLesson(
        title="درس مولّد بالاختبار",
        summary="ملخص كافٍ للتحقق من المسار المولّد كاملا",
        objectives=["هدف أول", "هدف ثانٍ"],
        content_md="ن" * 260,
        difficulty="beginner",
        est_minutes=25,
        code_samples=[
            {"language": "python", "title": "طباعة", "code": "print(1)", "explanation": "طباعة قيمة", "expected_output": "1"}
        ],
        quiz_questions=[
            {"text": "سؤال اختباري طويل", "kind": "single",
             "options": [{"text": "أ", "correct": True}, {"text": "ب", "correct": False}],
             "explanation": "لأن أ صحيحة"}
        ],
    )


# ---------------------------------------------------------------------
#  خطط اللغات (بلا قاعدة بيانات)
# ---------------------------------------------------------------------
def test_iter_language_lessons_scale_and_uniqueness():
    from core.config import settings

    plans = iter_language_lessons("python", "بايثون", icon="🐍")
    assert len(plans) == settings.lessons_per_language == 200
    slugs = {p.slug for p in plans}
    assert len(slugs) == len(plans), "عناوين/معرّفات مكرّرة"
    assert {p.stage_index for p in plans} == set(range(1, settings.GEN_STAGES + 1))
    assert plans[0].language == "python"
    assert plans[0].course_slug == "python-mastery"


def test_iter_language_lessons_respects_custom_shape():
    plans = iter_language_lessons("go", "غو", stages=2, per_stage=5)
    assert len(plans) == 10
    assert {p.stage_index for p in plans} == {1, 2}


# ---------------------------------------------------------------------
#  بناء المخطط (يلمس قاعدة البيانات)
# ---------------------------------------------------------------------
def test_build_language_outline_creates_browsable_lessons():
    from core.config import settings

    _reset_db()
    asyncio.run(_seed_python())

    async def run():
        async with SessionLocal() as s:
            res = await build_language_outline(s, "python", "بايثون", icon="🐍", use_ai=False)
        assert res["ok"], res
        assert res["lessons"] == settings.lessons_per_language
        async with SessionLocal() as s:
            course = await s.scalar(select(Course).where(Course.slug == "python-mastery"))
            assert course is not None
            stages = list((await s.execute(select(Stage).where(Stage.course_id == course.id))).scalars().all())
            assert len(stages) == settings.GEN_STAGES
            total = await s.scalar(
                select(func.count()).select_from(Lesson).join(Stage, Lesson.stage_id == Stage.id)
                .where(Stage.course_id == course.id)
            )
            assert total == settings.lessons_per_language
            outlines = await s.scalar(
                select(func.count()).select_from(Lesson).where(Lesson.status == "outline")
            )
            assert outlines == settings.lessons_per_language

    asyncio.run(run())


# ---------------------------------------------------------------------
#  الطابور والعامل (بـAI مزيّف)
# ---------------------------------------------------------------------
def test_enqueue_and_process_lesson_job_updates_in_place(monkeypatch):
    from core.config import settings

    _reset_db()
    asyncio.run(_seed_python())

    async def fake_generate(topic, language, difficulty="beginner", **kwargs):
        return _fake_lesson(), VerifyReport(passed=True)

    monkeypatch.setattr(jobs, "generate_lesson", fake_generate)

    async def run():
        async with SessionLocal() as s:
            res = await build_language_outline(s, "python", "بايثون", icon="🐍", use_ai=False)
            course = await s.scalar(select(Course).where(Course.slug == "python-mastery"))
            stage = await s.scalar(select(Stage).where(Stage.course_id == course.id).order_by(Stage.order_index))
            lesson = await s.scalar(select(Lesson).where(Lesson.stage_id == stage.id).order_by(Lesson.order_index))
            before = await s.scalar(
                select(func.count()).select_from(Lesson).where(Lesson.stage_id == stage.id)
            )
            lesson_id = lesson.id
            assert lesson.status == "outline"
            job = await jobs.enqueue_lesson(s, lesson_id)
            assert job is not None

        result = await jobs.process_job(job.id)
        assert result["ok"], result

        async with SessionLocal() as s:
            lesson = await s.get(Lesson, lesson_id)
            assert lesson.status == "published"
            assert lesson.is_verified is True
            assert lesson.content_md
            after = await s.scalar(
                select(func.count()).select_from(Lesson).where(Lesson.stage_id == lesson.stage_id)
            )
            assert after == before, "أُنشئ درس مكرّر بدل التحديث في مكانه"

    asyncio.run(run())


def test_enqueue_is_idempotent_and_queue_stats(monkeypatch):
    _reset_db()
    asyncio.run(_seed_python())

    async def run():
        async with SessionLocal() as s:
            await build_language_outline(s, "python", "بايثون", icon="🐍", use_ai=False)
            course = await s.scalar(select(Course).where(Course.slug == "python-mastery"))
            stage = await s.scalar(select(Stage).where(Stage.course_id == course.id).order_by(Stage.order_index))
            lesson = await s.scalar(select(Lesson).where(Lesson.stage_id == stage.id).order_by(Lesson.order_index))
            first = await jobs.enqueue_lesson(s, lesson.id)
            second = await jobs.enqueue_lesson(s, lesson.id)
            assert first is not None and second is None, "الإدراج يجب أن يكون غير مكرّر"
            st = await jobs.queue_stats(s)
            assert st["queued"] == 1

    asyncio.run(run())


def test_warm_enqueues_first_n(monkeypatch):
    from core.config import settings

    _reset_db()
    asyncio.run(_seed_python())

    async def run():
        async with SessionLocal() as s:
            await build_language_outline(s, "python", "بايثون", icon="🐍", use_ai=False)
            n = await jobs.enqueue_warm(s, "python", 5)
            assert n == 5
            st = await jobs.queue_stats(s)
            assert st["queued"] == 5

    asyncio.run(run())
