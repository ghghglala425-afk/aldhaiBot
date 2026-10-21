# -*- coding: utf-8 -*-
"""توليد المنهج دفعة واحدة (مسبق كامل) مع بوابة تحقق صارمة.

أمثلة:
  python -m pipeline.build_all --limit 3
  python -m pipeline.build_all --course python-security --publish
  python -m pipeline.build_all --only-missing
"""
from __future__ import annotations

import argparse
import asyncio
import time

from sqlalchemy import select

from core.config import settings
from core.db import SessionLocal, init_db
from core.logging import get_logger, setup_logging
from core.models import Lesson, Stage
from pipeline.generator import generate_lesson
from pipeline.sandbox_runner import docker_available
from pipeline.store_content import save_lesson
from pipeline.taxonomy import LessonPlan, iter_lessons, lesson_slug

setup_logging()
log = get_logger("pipeline.build")


async def _exists(session, plan: LessonPlan) -> bool:
    res = await session.execute(
        select(Lesson)
        .join(Stage, Lesson.stage_id == Stage.id)
        .where(Stage.slug == f"stage-{plan.stage_index}", Lesson.slug == lesson_slug(plan))
    )
    row = res.scalar_one_or_none()
    return bool(row and row.is_verified)


async def build(plans: list[LessonPlan], *, publish: bool, only_missing: bool, check_exec: bool) -> dict:
    sem = asyncio.Semaphore(max(1, settings.GEN_CONCURRENCY))
    stats = {"ok": 0, "failed": 0, "skipped": 0, "codes": 0}
    lock = asyncio.Lock()

    async def one(plan: LessonPlan) -> None:
        async with sem:
            async with SessionLocal() as session:
                if only_missing and await _exists(session, plan):
                    async with lock:
                        stats["skipped"] += 1
                    log.info("تخطي (موجود): %s - %s", plan.course_slug, plan.topic)
                    return
            try:
                lesson, report = await generate_lesson(
                    plan.topic, plan.language, plan.difficulty
                )
                if not report.passed:
                    async with lock:
                        stats["failed"] += 1
                    log.error(
                        "فشل التحقق: %s/%s — %s",
                        plan.course_slug, plan.topic, "; ".join(report.issues[:5]),
                    )
                    return
                async with SessionLocal() as session:
                    await save_lesson(session, plan, lesson, verified=True, publish=publish)
                async with lock:
                    stats["ok"] += 1
                    stats["codes"] += len(lesson.code_samples)
                log.info("✓ %s/%s (%d كود)", plan.course_slug, plan.topic, len(lesson.code_samples))
            except Exception as e:  # noqa: BLE001
                async with lock:
                    stats["failed"] += 1
                log.exception("خطأ في %s/%s: %s", plan.course_slug, plan.topic, e)

    await asyncio.gather(*(one(p) for p in plans))
    return stats


async def main() -> None:
    parser = argparse.ArgumentParser(description="توليد المنهج بالذكاء الاصطناعي")
    parser.add_argument("--course", action="append", help="slug كورس (يمكن تكراره)")
    parser.add_argument("--limit", type=int, default=0, help="حد أقصى لعدد الدروس")
    parser.add_argument("--only-missing", action="store_true", help="توليد ما لم يُولَّد فقط")
    parser.add_argument("--publish", action="store_true", help="نشر بعد التحقق")
    parser.add_argument("--no-exec", action="store_true", help="تعطيل تنفيذ الأكواد (تحقق نحوي)")
    args = parser.parse_args()

    if not settings.ai_configured:
        log.error("AI_API_KEY غير مضبوط — لا يمكن التوليد.")
        return

    await init_db()
    if await docker_available():
        log.info("التحقق بالتنفيذ عبر Docker مفعّل.")
    else:
        log.warning("Docker غير متاح — لن يُنفَّذ أي كود (التنفيذ على المضيف ممنوع)؛ تحقق نحوي فقط.")

    if args.no_exec:
        settings.VERIFY_EXEC = False

    plans = iter_lessons(args.course)
    if args.limit:
        plans = plans[: args.limit]
    log.info("عدد الدروس المطلوبة: %s", len(plans))

    t0 = time.time()
    stats = await build(plans, publish=args.publish or settings.AUTO_PUBLISH,
                        only_missing=args.only_missing, check_exec=settings.VERIFY_EXEC)
    log.info(
        "اكتمل: نجح=%s فشل=%s تخطي=%s أكواد=%s في %.1f ثانية",
        stats["ok"], stats["failed"], stats["skipped"], stats["codes"], time.time() - t0,
    )


if __name__ == "__main__":
    asyncio.run(main())
