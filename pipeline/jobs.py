# -*- coding: utf-8 -*-
"""طابور التوليد + عامل خلفي (Outline-first + Lazy fill).

- المخططات (outline): مهمة لكل لغة تُنشئ آلاف الدروس القابلة للتصفّح.
- الدروس (lesson): تُدرَج عند فتح درس مخطط (Lazy) أو تسخين أول N درس لكل لغة.
- العامل يعمل داخل عملية البوت بعدد تزامن قابل للضبط (GEN_WORKER_CONCURRENCY).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import time
from typing import Optional

from sqlalchemy import func, select

from core.config import settings
from core.db import SessionLocal
from core.logging import get_logger
from core.models import (
    CodeSample,
    Course,
    GenerationJob,
    Language,
    Lesson,
    Stage,
)
from pipeline.generator import generate_lesson
from pipeline.outline import build_language_outline
from pipeline.store_content import save_lesson
from pipeline.taxonomy import LessonPlan, language_icon, language_course_title

log = get_logger("pipeline.jobs")

_claim_lock = asyncio.Lock()
_stop = asyncio.Event()
_worker_task: asyncio.Task | None = None
_background_tasks: set[asyncio.Task] = set()


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# ---------------------------------------------------------------------
#  الإدراج
# ---------------------------------------------------------------------
async def enqueue(
    session,
    *,
    kind: str,
    dedup_key: str,
    language: Optional[str] = None,
    course_slug: Optional[str] = None,
    lesson_id: Optional[int] = None,
    topic: Optional[str] = None,
    priority: int = 0,
) -> Optional[GenerationJob]:
    """يُدرج مهمة (أو يعيد استخدامها). يُرجع المهمة أو None إن كانت مكرّرة نشطة."""
    if settings.GEN_QUEUE_MAX > 0:
        pending = await session.scalar(
            select(func.count())
            .select_from(GenerationJob)
            .where(GenerationJob.status.in_(("queued", "running")))
        )
        if (pending or 0) >= settings.GEN_QUEUE_MAX:
            log.warning("الطابور ممتلئ (%s) — رُفضت مهمة %s", pending, dedup_key)
            return None
    existing = await session.scalar(
        select(GenerationJob).where(GenerationJob.dedup_key == dedup_key)
    )
    if existing:
        if existing.status in {"queued", "running"}:
            return None
        if existing.status == "failed" and existing.attempts >= settings.GEN_JOB_MAX_ATTEMPTS:
            return None
        existing.status = "queued"
        existing.error = None
        existing.updated_at = _now()
        existing.priority = priority
        await session.commit()
        return existing
    job = GenerationJob(
        kind=kind, language=language, course_slug=course_slug, lesson_id=lesson_id,
        topic=topic, dedup_key=dedup_key, priority=priority,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def enqueue_lesson(session, lesson_id: int, *, priority: int = 5) -> Optional[GenerationJob]:
    return await enqueue(
        session, kind="lesson", dedup_key=f"lesson:{lesson_id}",
        lesson_id=lesson_id, priority=priority,
    )


async def enqueue_outline(session, language: str, *, priority: int = 1) -> Optional[GenerationJob]:
    return await enqueue(
        session, kind="outline", dedup_key=f"outline:{language}",
        language=language, priority=priority,
    )


async def outline_exists(session, language: str) -> bool:
    """هل مخطط هذه اللغة مبني بالفعل؟ (يمنع إعادة توليده بلا فائدة)."""
    from pipeline.taxonomy import language_course_slug

    course_slug = language_course_slug(language)
    n = await session.scalar(
        select(func.count())
        .select_from(Lesson)
        .join(Stage, Lesson.stage_id == Stage.id)
        .join(Course, Stage.course_id == Course.id)
        .where(Course.slug == course_slug)
    )
    return bool(n)


async def outline_in_progress(session, language: str) -> bool:
    """هل بناء المخطط جارٍ الآن؟"""
    job = await session.scalar(
        select(GenerationJob.id).where(
            GenerationJob.dedup_key == f"outline:{language}",
            GenerationJob.status.in_(("queued", "running")),
        )
    )
    return job is not None


async def enqueue_all_languages(session) -> int:
    rows = list((await session.execute(select(Language.slug))).scalars().all())
    added = 0
    for slug in rows:
        if await enqueue_outline(session, slug):
            added += 1
    return added


async def enqueue_warm(session, language: str, n: int | None = None) -> int:
    """يُدرج توليد أول N درس للغة (تسخين)."""
    n = n or settings.GEN_WARM_LESSONS
    course_slug = f"{language}-mastery"
    res = await session.execute(
        select(Lesson.id)
        .join(Stage, Lesson.stage_id == Stage.id)
        .join(Course, Stage.course_id == Course.id)
        .where(Course.slug == course_slug, Lesson.status == "outline")
        .order_by(Stage.order_index, Lesson.order_index)
        .limit(max(0, n))
    )
    added = 0
    for lid in res.scalars().all():
        if await enqueue_lesson(session, lid, priority=3):
            added += 1
    return added


# ---------------------------------------------------------------------
#  الحالة والإحصاء
# ---------------------------------------------------------------------
async def queue_stats(session) -> dict:
    rows = await session.execute(
        select(GenerationJob.status, func.count()).group_by(GenerationJob.status)
    )
    out = {"queued": 0, "running": 0, "done": 0, "failed": 0}
    for status, cnt in rows.all():
        out[status] = cnt
    out["outline_done"] = await session.scalar(
        select(func.count()).select_from(GenerationJob).where(
            GenerationJob.kind == "outline", GenerationJob.status == "done"
        )
    ) or 0
    out["lesson_done"] = await session.scalar(
        select(func.count()).select_from(GenerationJob).where(
            GenerationJob.kind == "lesson", GenerationJob.status == "done"
        )
    ) or 0
    return out


async def retry_failed(session) -> int:
    res = await session.execute(
        select(GenerationJob).where(GenerationJob.status == "failed")
    )
    n = 0
    for job in res.scalars().all():
        job.status = "queued"
        job.error = None
        job.updated_at = _now()
        n += 1
    await session.commit()
    return n


# ---------------------------------------------------------------------
#  المعالجة
# ---------------------------------------------------------------------
async def _claim_next(session) -> Optional[GenerationJob]:
    async with _claim_lock:
        job = await session.scalar(
            select(GenerationJob)
            .where(
                GenerationJob.status == "queued",
                GenerationJob.attempts < settings.GEN_JOB_MAX_ATTEMPTS,
            )
            .order_by(GenerationJob.priority.desc(), GenerationJob.id.asc())
            .limit(1)
        )
        if not job:
            return None
        job.status = "running"
        job.started_at = _now()
        job.attempts = (job.attempts or 0) + 1
        await session.commit()
        return job


async def _plan_from_lesson(session, lesson: Lesson) -> LessonPlan:
    stage = await session.get(Stage, lesson.stage_id)
    course = await session.get(Course, stage.course_id) if stage else None
    lang = None
    if lesson.language_slug:
        lang = await session.scalar(select(Language).where(Language.slug == lesson.language_slug))
    name_ar = (lang.name_ar or lang.name) if lang else (lesson.language_slug or "برمجة")
    return LessonPlan(
        course_slug=course.slug if course else f"{lesson.language_slug or 'x'}-mastery",
        course_title=course.title if course else language_course_title(name_ar),
        icon=course.icon if course and course.icon else language_icon(
            lesson.language_slug or "", lang.paradigm if lang else None
        ),
        language=lesson.language_slug or "python",
        stage=stage.title if stage else "المرحلة",
        stage_index=stage.order_index if stage else 1,
        topic=lesson.title,
        lesson_index=lesson.order_index,
        difficulty=lesson.difficulty,
        language_name=name_ar,
        outline_title=lesson.title,
        slug=lesson.slug,
        order_index=lesson.order_index or 0,
    )


async def _generate_lesson_job(session, job: GenerationJob, *, fast: bool = False) -> dict:
    lesson = await session.get(Lesson, job.lesson_id) if job.lesson_id else None
    if not lesson:
        return {"ok": False, "error": "الدرس غير موجود"}
    if lesson.status != "outline" and lesson.is_verified:
        return {"ok": True, "skipped": True}
    plan = await _plan_from_lesson(session, lesson)
    generated, report = await generate_lesson(
        plan.topic, plan.language, plan.difficulty, fast=fast,
    )
    if not report.passed:
        return {"ok": False, "error": "; ".join(report.issues[:5]) or "فشل التحقق"}
    row = await save_lesson(session, plan, generated, verified=True, publish=True)
    return {"ok": True, "lesson_id": row.id, "codes": len(generated.code_samples)}


async def _enrich_lesson_async(lesson_id: int) -> None:
    """يُثري أكواد درس مولَّد فورا (تشريح/استخدامات) في الخلفية بلا حجب المستخدم."""
    from pipeline.atlas import enrich_codes
    from pipeline.schema import GeneratedCode

    try:
        async with SessionLocal() as session:
            lesson = await session.get(Lesson, lesson_id)
            if not lesson:
                return
            rows = list(
                (await session.execute(
                    select(CodeSample)
                    .where(CodeSample.lesson_id == lesson_id)
                    .order_by(CodeSample.order_index)
                )).scalars().all()
            )
            if not rows or any(r.usages for r in rows):
                return
            codes = [
                GeneratedCode.model_validate(
                    {
                        "language": r.language,
                        "title": r.title,
                        "code": r.code,
                        "explanation": r.explanation or "",
                        "expected_output": r.expected_output or "",
                        "anatomy": r.anatomy or [],
                        "usages": r.usages or [],
                        "parameters": r.parameters or [],
                        "returns": r.returns or "",
                        "gotchas": r.gotchas or [],
                        "security_notes": r.security_notes or [],
                        "related": r.related or [],
                        "tags": r.tags or [],
                    }
                )
                for r in rows
            ]
            enriched = await enrich_codes(codes, lesson.language_slug or "python")
            for row, gc in zip(rows, enriched):
                row.anatomy = [a.model_dump() for a in gc.anatomy]
                row.usages = [u.model_dump() for u in gc.usages]
                row.parameters = [p.model_dump() for p in gc.parameters]
                row.returns = gc.returns
                row.gotchas = gc.gotchas
                row.security_notes = gc.security_notes
                row.related = gc.related
                row.tags = gc.tags
            await session.commit()
            log.info("أُثري الدرس #%s في الخلفية (موسوعة الأكواد)", lesson_id)
    except Exception as e:  # noqa: BLE001
        log.warning("تعذّر إثراء الدرس #%s في الخلفية: %s", lesson_id, e)


def _schedule_enrichment(lesson_id: int) -> None:
    task = asyncio.create_task(_enrich_lesson_async(lesson_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def generate_lesson_now(
    lesson_id: int, *, fast: bool = True, timeout: float = 150.0
) -> dict:
    """يولّد درسا مخططا فورا في مسار الاستدعاء (بلا انتظار العامل).

    يمنع التوليد المكرر عبر صف مهمة بحالة running. إن كانت هناك مهمة جارية
    بالفعل ينتظر نتيجتها بدل إهدار حصة AI.
    """
    key = f"lesson:{lesson_id}"
    deadline = time.monotonic() + max(10.0, timeout)
    job_id: int | None = None

    async with SessionLocal() as session:
        lesson = await session.get(Lesson, lesson_id)
        if not lesson:
            return {"ok": False, "error": "الدرس غير موجود"}
        if lesson.status != "outline" and lesson.content_md:
            return {"ok": True, "skipped": True}

        run_job: GenerationJob | None = None
        async with _claim_lock:
            job = await session.scalar(
                select(GenerationJob).where(GenerationJob.dedup_key == key)
            )
            if job and job.status == "running":
                job_id = job.id
            else:
                if job is None:
                    job = GenerationJob(
                        kind="lesson", dedup_key=key, lesson_id=lesson_id, priority=10
                    )
                    session.add(job)
                job.status = "running"
                job.error = None
                job.started_at = _now()
                job.updated_at = _now()
                job.attempts = (job.attempts or 0) + 1
                await session.commit()
                await session.refresh(job)
                job_id = job.id
                run_job = job

        if run_job is not None:
            try:
                res = await _generate_lesson_job(session, run_job, fast=fast)
            except Exception as e:  # noqa: BLE001
                log.exception("فشل التوليد الفوري للدرس #%s: %s", lesson_id, e)
                res = {"ok": False, "error": str(e)[:300]}

            job = await session.get(GenerationJob, job_id)
            if job:
                job.finished_at = _now()
                job.updated_at = _now()
                job.status = "done" if res.get("ok") else "failed"
                job.error = None if res.get("ok") else (res.get("error") or "خطأ")
                await session.commit()
            if res.get("ok") and fast:
                _schedule_enrichment(lesson_id)
            return res

    # مهمة جارية بالفعل: انتظر انتهاءها بدل التوليد المكرر.
    while time.monotonic() < deadline:
        await asyncio.sleep(1.5)
        async with SessionLocal() as session:
            lesson = await session.get(Lesson, lesson_id)
            if lesson and lesson.status != "outline" and lesson.content_md:
                return {"ok": True, "skipped": True}
            job = await session.get(GenerationJob, job_id)
            if job and job.status == "failed":
                return {"ok": False, "error": job.error or "فشل التوليد"}
    return {
        "ok": False,
        "error": "انتهت مهلة الانتظار — أُكمل التوليد في الخلفية",
        "pending": True,
    }


async def _outline_job(session, job: GenerationJob) -> dict:
    lang = None
    if job.language:
        lang = await session.scalar(select(Language).where(Language.slug == job.language))
    if not lang:
        return {"ok": False, "error": f"لغة غير معروفة: {job.language}"}
    res = await build_language_outline(
        session, lang.slug, lang.name_ar or lang.name,
        icon=language_icon(lang.slug, lang.paradigm), use_ai=True,
    )
    if res.get("ok"):
        await enqueue_warm(session, lang.slug)
    return res


async def process_job(job_id: int) -> dict:
    async with SessionLocal() as session:
        job = await session.get(GenerationJob, job_id)
        if not job:
            return {"ok": False, "error": "مهمة غير موجودة"}
        if job.status == "queued":
            job.status = "running"
            job.started_at = _now()
            job.attempts = (job.attempts or 0) + 1
            await session.commit()
        elif job.status != "running":
            return {"ok": False, "error": "مهمة غير نشطة"}
        try:
            if job.kind == "outline":
                res = await _outline_job(session, job)
            elif job.kind == "lesson":
                res = await _generate_lesson_job(session, job)
            else:
                res = {"ok": False, "error": f"نوع غير مدعوم: {job.kind}"}
        except Exception as e:  # noqa: BLE001
            log.exception("فشل المهمة #%s: %s", job.id, e)
            res = {"ok": False, "error": str(e)[:300]}

        job = await session.get(GenerationJob, job_id)
        if job:
            job.finished_at = _now()
            job.updated_at = _now()
            job.status = "done" if res.get("ok") else "failed"
            job.error = None if res.get("ok") else (res.get("error") or "خطأ")
            await session.commit()
        log.info("مهمة #%s (%s) → %s", job_id, job.kind if job else "?", res.get("ok"))
        return res


# ---------------------------------------------------------------------
#  العامل الخلفي
# ---------------------------------------------------------------------
async def worker_loop(stop_event: asyncio.Event | None = None) -> None:
    stop = stop_event or _stop
    tasks: set[asyncio.Task] = set()
    failures = 0
    log.info("عامل التوليد يعمل (تزامن=%s).", settings.GEN_WORKER_CONCURRENCY)
    try:
        while not stop.is_set():
            if not settings.ai_configured:
                await asyncio.sleep(max(10, settings.GEN_QUEUE_POLL))
                continue
            if len(tasks) >= max(1, settings.GEN_WORKER_CONCURRENCY):
                await asyncio.sleep(1)
                continue
            async with SessionLocal() as session:
                job = await _claim_next(session)
            if not job:
                await asyncio.sleep(settings.GEN_QUEUE_POLL)
                failures = 0
                continue
            t = asyncio.create_task(process_job(job.id))
            tasks.add(t)
            t.add_done_callback(tasks.discard)
            failures = 0
            # تراجع أسّي عند تكرار فشل الحصص (429) حتى لا نحرق اليوم كله
            failed = await _recent_failures()
            if failed:
                failures += 1
                delay = min(60 * (2 ** (failures - 1)), 1800)
                log.warning("فشل متكرر (%s) — إيقاف مؤقت %ss", failed, delay)
                await asyncio.sleep(delay)
    finally:
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        log.info("توقّف عامل التوليد.")


async def _recent_failures() -> int:
    """عدد المهام الفاشلة حديثا (آخر 10 دقائق) — مؤشر نفاد الحصة."""
    since = _now() - dt.timedelta(minutes=10)
    async with SessionLocal() as session:
        return int(
            await session.scalar(
                select(func.count())
                .select_from(GenerationJob)
                .where(GenerationJob.status == "failed", GenerationJob.finished_at >= since)
            )
            or 0
        )


def start_worker() -> asyncio.Task:
    global _worker_task
    _stop.clear()
    if _worker_task and not _worker_task.done():
        return _worker_task
    _worker_task = asyncio.create_task(worker_loop())
    return _worker_task


async def stop_worker() -> None:
    _stop.set()
    if _worker_task:
        try:
            await asyncio.wait_for(_worker_task, timeout=30)
        except Exception:  # noqa: BLE001
            _worker_task.cancel()


async def kick(language: str | None = None) -> dict:
    """تشغيل سريع من البوت: إدراج مخطط لغة (أو كل اللغات) + تسخين."""
    async with SessionLocal() as session:
        if language:
            job = await enqueue_outline(session, language)
            return {"ok": True, "queued": bool(job), "language": language}
        n = await enqueue_all_languages(session)
        return {"ok": True, "queued": n}
