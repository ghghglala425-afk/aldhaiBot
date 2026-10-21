# -*- coding: utf-8 -*-
"""تصفّح اللغات العالمية (48 لغة) ومراحلها ودروسها المخطّطة."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes
from sqlalchemy import select

from app.handlers.common import current_user, spawn
from app.keyboards import languages_kb
from app.pagination import nav_row, slice_page, total_pages
from core.config import settings
from core.db import SessionLocal
from core.logging import get_logger
from core.models import Course, Language, Lesson, Stage
from pipeline.outline import outline_language_slug
from pipeline.taxonomy import language_course_slug, language_icon
from app import tg

log = get_logger("bot.languages")

LANGS_PER_PAGE = 12
LESSONS_PER_PAGE = 12

_STATUS_ICON = {"published": "✅", "verified": "🟦", "outline": "🕓", "draft": "✏️"}


async def _lang_rows() -> list[dict]:
    async with SessionLocal() as s:
        rows = list((await s.execute(select(Language).order_by(Language.id))).scalars().all())
    return [
        {
            "slug": l.slug,
            "name": l.name,
            "name_ar": l.name_ar or l.name,
            "icon": language_icon(l.slug, l.paradigm),
        }
        for l in rows
    ]


async def languages_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    langs = await _lang_rows()
    if not langs:
        await tg.send_text(update.effective_message, "لا توجد لغات مسجّلة. شغّل البذور (seed).")
        return
    pages = total_pages(len(langs), LANGS_PER_PAGE)
    text = (
        "🌍 *لغات البرمجة*\n\n"
        f"الإجمالي: {len(langs)} لغة — اختر لغة لعرض مسارها الكامل "
        f"({settings.lessons_per_language} درس/لغة)."
    )
    await tg.send_text(update.effective_message, 
        text, parse_mode=ParseMode.MARKDOWN, reply_markup=languages_kb(langs, 0, pages, LANGS_PER_PAGE)
    )


async def languages_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    page = int(q.data.split(":")[1])
    langs = await _lang_rows()
    pages = total_pages(len(langs), LANGS_PER_PAGE)
    await q.edit_message_reply_markup(reply_markup=languages_kb(langs, page, pages, LANGS_PER_PAGE))


async def language_open(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    await _render_language(q, q.data.split(":", 1)[1])


async def _render_language(q, slug: str) -> None:
    """يعرض صفحة اللغة، ويبني مخططها محليا وفورا إن لم يكن موجودا (بلا AI)."""
    course_slug = language_course_slug(slug)
    async with SessionLocal() as s:
        lang = await s.scalar(select(Language).where(Language.slug == slug))
        if not lang:
            await tg.edit_text(q, "اللغة غير موجودة.")
            return
        course = await s.scalar(select(Course).where(Course.slug == course_slug))
        if not course:
            try:
                await outline_language_slug(s, slug, use_ai=False)
            except Exception as e:  # noqa: BLE001
                log.warning("تعذّر بناء مخطط %s محليا: %s", slug, e)
                await s.rollback()
            course = await s.scalar(select(Course).where(Course.slug == course_slug))
        stages = []
        counts: dict[int, dict] = {}
        if course:
            stages = list(
                (await s.execute(
                    select(Stage).where(Stage.course_id == course.id).order_by(Stage.order_index)
                )).scalars().all()
            )
            for st in stages:
                rows = list((await s.execute(select(Lesson).where(Lesson.stage_id == st.id))).scalars().all())
                counts[st.order_index] = {
                    "total": len(rows),
                    "ready": sum(1 for r in rows if r.status in {"published", "verified"}),
                }
    name_ar = lang.name_ar or lang.name
    icon = language_icon(lang.slug, lang.paradigm)
    built = bool(course and counts)
    total = sum(c["total"] for c in counts.values()) or settings.lessons_per_language
    ready = sum(c["ready"] for c in counts.values())

    lines = [
        f"{icon} *إتقان {tg.escape_md(name_ar)}*",
        f"النمط: {lang.paradigm or '—'} · الصعوبة: {lang.difficulty}",
        f"الدروس: {ready}/{total} جاهز" if built else f"المخطط: {settings.lessons_per_language} درس (غير مبني بعد)",
        "",
    ]
    rows: list[list[InlineKeyboardButton]] = []
    if built:
        for st in stages:
            c = counts.get(st.order_index, {"total": 0, "ready": 0})
            rows.append([
                InlineKeyboardButton(
                    f"{st.title} ({c['ready']}/{c['total']})",
                    callback_data=f"langst:{slug}:{st.order_index}:0",
                )
            ])
        rows.append([InlineKeyboardButton("🔥 تسخين أول دروس", callback_data=f"langwarm:{slug}")])
    else:
        lines.append(
            "اضغط «🧩 بناء المخطط» لإنشاء الخريطة الكاملة فورا "
            "(دون أي نداء AI — الدروس تُبنى عند فتحها)."
        )
        rows.append([InlineKeyboardButton("🧩 بناء المخطط", callback_data=f"langbuild:{slug}")])
    rows.append([InlineKeyboardButton("⬅️ كل اللغات", callback_data="langs:0")])
    await tg.edit_text(q, 
        "\n".join(lines)[:3900], parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(rows)
    )

    # بناء تلقائي تدريجي لكل دروس اللغة في الخلفية (فتح أي درس يصبح فوريا).
    if built and settings.GEN_PREBUILD_ON_OPEN and settings.ai_configured:
        spawn(_auto_prebuild(slug))


async def _auto_prebuild(
    slug: str, *, stage_index: int | None = None, priority: int | None = None
) -> None:
    """يُدرج دروس اللغة المخطّطة (أو مرحلة) للبناء التدريجي في الخلفية بأولوية منخفضة."""
    from pipeline import jobs

    try:
        async with SessionLocal() as s:
            n = await jobs.enqueue_prebuild(s, slug, stage_index=stage_index, priority=priority)
        if n:
            log.info("بناء تلقائي خلفي: أُدرجت %s مهمة للغة %s (مرحلة=%s)", n, slug, stage_index)
    except Exception as e:  # noqa: BLE001
        log.warning("تعذّر البناء التلقائي للغة %s: %s", slug, e)


async def stage_lessons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    _, slug, si, page = q.data.split(":")
    si, page = int(si), int(page)
    course_slug = language_course_slug(slug)
    async with SessionLocal() as s:
        course = await s.scalar(select(Course).where(Course.slug == course_slug))
        stage = None
        lessons: list[Lesson] = []
        if course:
            stage = await s.scalar(
                select(Stage).where(Stage.course_id == course.id, Stage.order_index == si)
            )
        if stage:
            lessons = list(
                (await s.execute(
                    select(Lesson).where(Lesson.stage_id == stage.id).order_by(Lesson.order_index)
                )).scalars().all()
            )
    if not stage or not lessons:
        await tg.edit_text(q, "المرحلة غير متاحة.")
        return
    pages = total_pages(len(lessons), LESSONS_PER_PAGE)
    chunk = slice_page(lessons, page, LESSONS_PER_PAGE)
    lines = [f"📚 *{stage.title}* — {len(lessons)} درس", ""]
    rows: list[list[InlineKeyboardButton]] = []
    for l in chunk:
        icon = _STATUS_ICON.get(l.status, "•")
        lines.append(f"{icon} {tg.escape_md(l.title)}")
        rows.append([InlineKeyboardButton(f"{icon} {tg.escape_md(l.title)[:46]}", callback_data=f"lesson:{l.id}")])
    rows.append(nav_row(f"langst:{slug}:{si}", page, pages))
    rows.append([InlineKeyboardButton("⬅️ رجوع", callback_data=f"lang:{slug}")])
    await tg.edit_text(q, 
        "\n".join(lines)[:3900], parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(rows)
    )

    # المرحلة التي يتصفّحها المستخدم الآن لها الأولوية في البناء الخلفي.
    if settings.GEN_PREBUILD_ON_OPEN and settings.ai_configured:
        spawn(_auto_prebuild(slug, stage_index=si, priority=6))


async def language_build(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يبني مخطط اللغة محليا وفورا (بلا AI)، ثم يعرض صفحتها."""
    q = update.callback_query
    slug = q.data.split(":", 1)[1]
    await q.answer("⏳ أبني المخطط الآن…")
    async with SessionLocal() as s:
        try:
            await outline_language_slug(s, slug, use_ai=False)
        except Exception as e:  # noqa: BLE001
            log.warning("تعذّر بناء مخطط %s: %s", slug, e)
            await s.rollback()
    await _render_language(q, slug)


async def language_warm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """تسخين أول دروس اللغة — متاح لكل المستخدمين بلا حدود زمنية."""
    q = update.callback_query
    slug = q.data.split(":", 1)[1]
    if not settings.ai_configured:
        await q.answer("AI غير مضبوط.", show_alert=True)
        return

    from pipeline import jobs

    # المشرف يبني كل دروس اللغة؛ المستخدم العادي دفعة محدودة (حماية الحصة المجانية)
    is_admin_user = update.effective_user.id in settings.admin_ids
    limit = (settings.GEN_PREBUILD_MAX or 0) if is_admin_user else 5

    async with SessionLocal() as s:
        n = await jobs.enqueue_prebuild(s, slug, priority=3, limit=limit)
    await q.answer(
        f"أُدرج بناء {n} درسا في الخلفية 🔥" if n else "لا توجد دروس جديدة لبنائها ✅",
        show_alert=True,
    )


def register_handlers(app) -> None:
    app.add_handler(CommandHandler("languages", languages_cmd))
    app.add_handler(CallbackQueryHandler(languages_page, pattern=r"^langs:\d+$"))
    app.add_handler(CallbackQueryHandler(language_open, pattern=r"^lang:[\w\-]+$"))
    app.add_handler(CallbackQueryHandler(stage_lessons, pattern=r"^langst:[\w\-]+:\d+:\d+$"))
    app.add_handler(CallbackQueryHandler(language_build, pattern=r"^langbuild:[\w\-]+$"))
    app.add_handler(CallbackQueryHandler(language_warm, pattern=r"^langwarm:[\w\-]+$"))
