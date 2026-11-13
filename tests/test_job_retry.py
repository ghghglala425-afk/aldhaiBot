# -*- coding: utf-8 -*-
"""إعادة محاولة مهام التوليد: تهدئة بعد الفشل، سقف كلي، وأخطاء الحصة."""
from __future__ import annotations

import asyncio
import datetime as dt

from core.config import settings
from core.db import SessionLocal, engine, init_db
from core.models import Base, Course, GenerationJob, Lesson, Stage
from pipeline import jobs


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _reset_db() -> None:
    async def _drop() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    asyncio.run(_drop())
    asyncio.run(init_db())


def _seed_lesson() -> int:
    async def _go() -> int:
        async with SessionLocal() as s:
            course = Course(slug="c1", title="كورس اختبار")
            s.add(course)
            await s.flush()
            stage = Stage(course_id=course.id, slug="st1", title="مرحلة", order_index=1)
            s.add(stage)
            await s.flush()
            lesson = Lesson(
                stage_id=stage.id, slug="l1", title="درس", order_index=1,
                status="outline", content_md="",
            )
            s.add(lesson)
            await s.commit()
            return lesson.id

    return asyncio.run(_go())


def _set_job(job: GenerationJob, *, status: str, attempts: int,
             finished_at: dt.datetime | None = None) -> None:
    job.status = status
    job.attempts = attempts
    job.finished_at = finished_at


def test_failed_job_waits_for_cooldown_then_retries():
    _reset_db()
    lesson_id = _seed_lesson()

    async def run():
        async with SessionLocal() as s:
            job = await jobs.enqueue_lesson(s, lesson_id)
            assert job is not None
            _set_job(
                job, status="failed", attempts=settings.GEN_JOB_MAX_ATTEMPTS,
                finished_at=_now() - dt.timedelta(minutes=2),
            )
            await s.commit()
            assert await jobs.enqueue_lesson(s, lesson_id) is None, "لم تنته التهدئة بعد"

            job = await s.get(GenerationJob, job.id)
            job.finished_at = _now() - dt.timedelta(
                minutes=settings.GEN_JOB_RETRY_COOLDOWN_MINUTES + 5
            )
            await s.commit()
            again = await jobs.enqueue_lesson(s, lesson_id)
            assert again is not None and again.status == "queued"

    asyncio.run(run())


def test_failed_job_stops_at_total_cap():
    _reset_db()
    lesson_id = _seed_lesson()

    async def run():
        async with SessionLocal() as s:
            job = await jobs.enqueue_lesson(s, lesson_id)
            _set_job(
                job, status="failed",
                attempts=settings.GEN_JOB_MAX_TOTAL_ATTEMPTS,
                finished_at=_now() - dt.timedelta(days=7),
            )
            await s.commit()
            assert await jobs.enqueue_lesson(s, lesson_id) is None

    asyncio.run(run())


def test_retry_failed_requeues_blocked_job_and_claim_takes_it():
    _reset_db()
    lesson_id = _seed_lesson()

    async def run():
        async with SessionLocal() as s:
            job = await jobs.enqueue_lesson(s, lesson_id)
            _set_job(job, status="failed", attempts=9, finished_at=_now())
            await s.commit()

            assert await jobs.retry_failed(s) == 1
            claimed = await jobs._claim_next(s)
            assert claimed is not None and claimed.id == job.id
            assert claimed.status == "running"
            assert claimed.attempts == 10

    asyncio.run(run())


def test_quota_failure_does_not_consume_attempts(monkeypatch):
    from pipeline.ai import AIError

    _reset_db()
    lesson_id = _seed_lesson()

    async def fake_generate(*args, **kwargs):
        raise AIError(
            "فشل كل المزوّدين: gemini:q7: نفدت حصته اليومية | gemini:nW: نفدت حصته اليومية"
        )

    monkeypatch.setattr(jobs, "generate_lesson", fake_generate)

    async def run():
        async with SessionLocal() as s:
            job = await jobs.enqueue_lesson(s, lesson_id)
            job_id = job.id
        res = await jobs.process_job(job_id)
        assert not res["ok"]
        async with SessionLocal() as s:
            job = await s.get(GenerationJob, job_id)
            assert job.status == "failed"
            assert job.attempts == 0, "خطأ الحصة عطل مؤقت ولا يحجب المهمة"

    asyncio.run(run())


def test_real_failure_counts_attempt(monkeypatch):
    _reset_db()
    lesson_id = _seed_lesson()

    async def fake_generate(*args, **kwargs):
        raise ValueError("مخرجات غير صالحة")

    monkeypatch.setattr(jobs, "generate_lesson", fake_generate)

    async def run():
        async with SessionLocal() as s:
            job = await jobs.enqueue_lesson(s, lesson_id)
            job_id = job.id
        res = await jobs.process_job(job_id)
        assert not res["ok"]
        async with SessionLocal() as s:
            job = await s.get(GenerationJob, job_id)
            assert job.status == "failed"
            assert job.attempts == 1

    asyncio.run(run())
