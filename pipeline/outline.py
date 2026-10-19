# -*- coding: utf-8 -*-
"""مولّد المخطط (Outline-first).

لكل لغة: نداء AI واحد (بموديل سريع) يُنتج عناوين الدروس موزّعة على المراحل،
ثم تُحفظ كدروس «مخطط» قابلة للتصفّح فورا (بلا محتوى). يُولَّد المحتوى لاحقا عند الطلب.

آمن تماما: عند غياب AI أو فشله، يُستخدم عنوان حتمي من taxonomy فلا تفشل العملية.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.logging import get_logger
from core.models import Course, Language, Lesson, Stage
from pipeline.ai import AIError, chat_json
from pipeline.store_content import ensure_course, ensure_stage
from pipeline.taxonomy import LessonPlan, language_icon, lesson_slug, stage_titles

log = get_logger("pipeline.outline")

SYSTEM = """أنت خبير مناهج برمجية. ستحصل على لغة برمجة وقائمة مراحل، ولكل مرحلة عدد دروس.
أعد عناوين دروس عربية واضحة ومتدرّجة (بلا تكرار)، بصيغة JSON:
{"stages":[{"index":1,"titles":["عنوان","عنوان", ...]}]}
قواعد: التزم بعدد العناوين لكل مرحلة تماما، ورتّبها من الأسهل إلى الأصعب."""


def _outline_chunks(plans: list[LessonPlan], per_stage: int) -> list[list[LessonPlan]]:
    out: list[list[LessonPlan]] = []
    for i in range(0, len(plans), max(1, per_stage)):
        out.append(plans[i : i + max(1, per_stage)])
    return out


async def suggest_titles(
    language: str, name_ar: str, plans: list[LessonPlan], per_stage: int
) -> dict[int, list[str]]:
    """نداء واحد لكل مرحلة (لتقليل الحجم) — يُرجع {stage_index: [titles]}."""
    result: dict[int, list[str]] = {}
    defined = stage_titles()
    for block in _outline_chunks(plans, per_stage):
        si = block[0].stage_index
        stage_title = defined[si - 1][0] if si - 1 < len(defined) else block[0].stage
        user = (
            f"لغة البرمجة: {name_ar} ({language})\n"
            f"المرحلة {si}: {stage_title}\n"
            f"عدد الدروس المطلوب: {len(block)}\n"
            "الموضوعات المقترحة لهذه المرحلة (استرشد بها ولا تلتزم حرفيا):\n- "
            + "\n- ".join(p.topic for p in block)
        )
        try:
            data = await chat_json(
                SYSTEM, user, temperature=0.5,
                model=settings.outline_model, max_tokens=min(settings.AI_MAX_TOKENS, 8192),
            )
        except AIError as e:
            log.warning("فشل اقتراح عناوين المرحلة %s: %s", si, e)
            continue
        for item in data.get("stages", []) or []:
            try:
                idx = int(item.get("index", si))
                titles = [str(t).strip() for t in (item.get("titles") or []) if str(t).strip()]
            except Exception:  # noqa: BLE001
                continue
            if titles:
                result[idx] = titles
    return result


async def build_language_outline(
    session: AsyncSession,
    language: str,
    name_ar: str,
    *,
    icon: str = "📘",
    use_ai: bool = True,
) -> dict:
    """ينشئ كورس اللغة + مراحله + دروسه (status='outline'). يُرجع إحصاءات."""
    from pipeline.taxonomy import iter_language_lessons

    plans = iter_language_lessons(language, name_ar, icon=icon)
    if not plans:
        return {"ok": False, "error": "لا توجد خطة"}

    per_stage = max(1, settings.GEN_LESSONS_PER_STAGE)
    if use_ai and settings.ai_configured:
        titles = await suggest_titles(language, name_ar, plans, per_stage)
        for p in plans:
            t = titles.get(p.stage_index)
            if t and 0 < p.lesson_index <= len(t):
                p.outline_title = t[p.lesson_index - 1]

    course = await ensure_course(session, plans[0])
    by_stage: dict[int, Stage] = {}
    created = 0
    for plan in plans:
        if plan.stage_index not in by_stage:
            by_stage[plan.stage_index] = await ensure_stage(session, course, plan)
        stage = by_stage[plan.stage_index]
        slug = lesson_slug(plan)
        existing = await session.scalar(
            select(Lesson).where(Lesson.stage_id == stage.id, Lesson.slug == slug)
        )
        if existing:
            if existing.status == "outline" and plan.outline_title:
                existing.title = plan.outline_title
            continue
        session.add(
            Lesson(
                stage_id=stage.id,
                slug=slug,
                title=plan.outline_title or plan.topic,
                summary=f"درس مخطط في {name_ar}: {plan.topic}. سيُولَّد المحتوى الكامل عند فتحه.",
                objectives=[],
                content_md=None,
                language_slug=language,
                difficulty=plan.difficulty,
                est_minutes=25,
                order_index=plan.lesson_index,
                xp_reward=50,
                min_score=70,
                status="outline",
                is_verified=False,
            )
        )
        created += 1
    await session.commit()
    log.info("مخطط %s: %s درس (كورس %s)", language, created, course.slug)
    return {"ok": True, "course_slug": course.slug, "lessons": created, "total": len(plans)}


async def all_languages(session: AsyncSession) -> list[Language]:
    res = await session.execute(select(Language).order_by(Language.id))
    return list(res.scalars().all())


async def outline_language_slug(session: AsyncSession, slug: str, *, use_ai: bool = True) -> dict:
    lang = await session.scalar(select(Language).where(Language.slug == slug))
    if not lang:
        return {"ok": False, "error": f"اللغة {slug} غير مسجّلة"}
    return await build_language_outline(
        session, lang.slug, lang.name_ar or lang.name,
        icon=language_icon(lang.slug, lang.paradigm), use_ai=use_ai,
    )
