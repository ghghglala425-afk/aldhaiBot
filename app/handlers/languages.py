# -*- coding: utf-8 -*-
"""تصفّح اللغات العالمية (48 لغة) ومراحلها ودروسها المخطّطة."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes
from sqlalchemy import select

from app.handlers.admin import is_admin
from app.handlers.common import current_user
from app.keyboards import languages_kb
from app.pagination import nav_row, slice_page, total_pages
from core.config import settings
from core.db import SessionLocal
from core.logging import get_logger
from core.models import Course, Language, Lesson, Stage
from pipeline.taxonomy import iter_language_lessons, language_course_slug, language_icon

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
        await update.effective_message.reply_text("لا توجد لغات مسجّلة. شغّل البذور (seed).")
        return
    pages = total_pages(len(langs), LANGS_PER_PAGE)
    text = (
        "🌍 *لغات البرمجة*\n\n"
        f"الإجمالي: {len(langs)} لغة — اختر لغة لعرض مسارها الكامل "
        f"({settings.lessons_per_language} درس/لغة)."
    )
    await update.effective_message.reply_text(
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
    slug = q.data.split(":", 1)[1]
    course_slug = language_course_slug(slug)
    async with SessionLocal() as s:
        lang = await s.scalar(select(Language).where(Language.slug == slug))
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
    if not lang:
        await q.edit_message_text("اللغة غير موجودة.")
        return
    name_ar = lang.name_ar or lang.name
    icon = language_icon(lang.slug, lang.paradigm)
    built = bool(course and counts)
    total = sum(c["total"] for c in counts.values()) or settings.lessons_per_language
    ready = sum(c["ready"] for c in counts.values())

    lines = [
        f"{icon} *إتقان {name_ar}*",
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
        lines.append("اضغط «بناء المخطط» لإنشاء الخريطة الكاملة فورا (نداء AI واحد).")
        rows.append([InlineKeyboardButton("🧩 بناء المخطط", callback_data=f"langbuild:{slug}")])
    rows.append([InlineKeyboardButton("⬅️ كل اللغات", callback_data="langs:0")])
    await q.edit_message_text(
        "\n".join(lines)[:3900], parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(rows)
    )


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
        await q.edit_message_text("المرحلة غير متاحة.")
        return
    pages = total_pages(len(lessons), LESSONS_PER_PAGE)
    chunk = slice_page(lessons, page, LESSONS_PER_PAGE)
    lines = [f"📚 *{stage.title}* — {len(lessons)} درس", ""]
    rows: list[list[InlineKeyboardButton]] = []
    for l in chunk:
        icon = _STATUS_ICON.get(l.status, "•")
        lines.append(f"{icon} {l.title}")
        rows.append([InlineKeyboardButton(f"{icon} {l.title[:46]}", callback_data=f"lesson:{l.id}")])
    rows.append(nav_row(f"langst:{slug}:{si}", page, pages))
    rows.append([InlineKeyboardButton("⬅️ رجوع", callback_data=f"lang:{slug}")])
    await q.edit_message_text(
        "\n".join(lines)[:3900], parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(rows)
    )


async def language_build(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    slug = q.data.split(":", 1)[1]
    if not is_admin(update.effective_user.id):
        await q.answer("🔒 التوليد متاح للمشرف فقط.", show_alert=True)
        return
    if not settings.ai_configured:
        await q.answer("AI غير مضبوط — لا يمكن بناء المخطط.", show_alert=True)
        return
    from pipeline import jobs

    async with SessionLocal() as s:
        job = await jobs.enqueue_outline(s, slug)
    await q.answer("أُدرج بناء المخطط في الطابور ✅" if job else "المخطط قيد البناء بالفعل ⏳", show_alert=True)
    log.info("طلب بناء مخطط %s (job=%s)", slug, job.id if job else None)


async def language_warm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    slug = q.data.split(":", 1)[1]
    if not is_admin(update.effective_user.id):
        await q.answer("🔒 التسخين متاح للمشرف فقط.", show_alert=True)
        return
    if not settings.ai_configured:
        await q.answer("AI غير مضبوط.", show_alert=True)
        return
    from pipeline import jobs

    async with SessionLocal() as s:
        n = await jobs.enqueue_warm(s, slug)
    await q.answer(f"أُدرج تسخين {n} درسا 🔥" if n else "كل الدروس مسخّنة مسبقا ✅", show_alert=True)


def register_handlers(app) -> None:
    app.add_handler(CommandHandler("languages", languages_cmd))
    app.add_handler(CallbackQueryHandler(languages_page, pattern=r"^langs:\d+$"))
    app.add_handler(CallbackQueryHandler(language_open, pattern=r"^lang:[\w\-]+$"))
    app.add_handler(CallbackQueryHandler(stage_lessons, pattern=r"^langst:[\w\-]+:\d+:\d+$"))
    app.add_handler(CallbackQueryHandler(language_build, pattern=r"^langbuild:[\w\-]+$"))
    app.add_handler(CallbackQueryHandler(language_warm, pattern=r"^langwarm:[\w\-]+$"))
