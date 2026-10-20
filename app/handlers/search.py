# -*- coding: utf-8 -*-
"""البحث الموحّد عبر اللغات والكورسات والدروس والأكواد."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from sqlalchemy import or_, select

from core.db import SessionLocal
from core.logging import get_logger
from core.models import CodeSample, Course, Language, Lesson
from app import tg

log = get_logger("bot.search")

AWAIT_QUERY = 600
MAX_PER_KIND = 8


async def _search(term: str) -> dict:
    like = f"%{term}%"
    async with SessionLocal() as s:
        courses = list((await s.execute(
            select(Course).where(or_(Course.title.ilike(like), Course.slug.ilike(like))).limit(MAX_PER_KIND)
        )).scalars().all())
        lessons = list((await s.execute(
            select(Lesson).where(or_(Lesson.title.ilike(like), Lesson.summary.ilike(like))).limit(MAX_PER_KIND)
        )).scalars().all())
        codes = list((await s.execute(
            select(CodeSample).where(or_(CodeSample.title.ilike(like), CodeSample.code.ilike(like))).limit(MAX_PER_KIND)
        )).scalars().all())
        langs = list((await s.execute(
            select(Language).where(or_(
                Language.name.ilike(like), Language.name_ar.ilike(like), Language.slug.ilike(like)
            )).limit(MAX_PER_KIND)
        )).scalars().all())
    return {"courses": courses, "lessons": lessons, "codes": codes, "langs": langs}


async def _render(update: Update, term: str) -> None:
    from app import ratelimit

    if not await ratelimit.guard(update, "search"):
        return
    res = await _search(term)
    total = sum(len(v) for v in res.values())
    if not total:
        await tg.send_text(update.effective_message, f"🔎 لا نتائج لـ «{term}».")
        return
    lines = [f"🔎 *نتائج «{term}»*", ""]
    rows: list[list[InlineKeyboardButton]] = []
    if res["langs"]:
        lines.append("*اللغات:*")
        lines.extend(f"• {l.name_ar or l.name}" for l in res["langs"])
        rows.append([InlineKeyboardButton(f"🌍 {l.name_ar or l.name}", callback_data=f"lang:{l.slug}") for l in res["langs"][:3]])
    if res["courses"]:
        lines.append("\n*الكورسات:*")
        lines.extend(f"• {c.title}" for c in res["courses"])
        rows.extend([[InlineKeyboardButton(f"📘 {c.title[:46]}", callback_data=f"course:{c.id}")] for c in res["courses"][:5]])
    if res["lessons"]:
        lines.append("\n*الدروس:*")
        lines.extend(f"• {l.title}" for l in res["lessons"])
        rows.extend([[InlineKeyboardButton(f"📖 {l.title[:46]}", callback_data=f"lesson:{l.id}")] for l in res["lessons"][:5]])
    if res["codes"]:
        lines.append("\n*الأكواد:*")
        lines.extend(f"• {c.title}" for c in res["codes"])
        rows.extend([[InlineKeyboardButton(f"💻 {c.title[:46]}", callback_data=f"code:{c.id}")] for c in res["codes"][:5]])
    await tg.send_text(update.effective_message, 
        "\n".join(lines)[:3900],
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(rows) if rows else None,
    )


async def search_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    term = (update.message.text or "").partition(" ")[2].strip()
    if term:
        await _render(update, term)
        return ConversationHandler.END
    await tg.send_text(update.message, "🔎 أرسل كلمة البحث (اكتب /cancel للإلغاء):")
    return AWAIT_QUERY


async def got_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await _render(update, (update.message.text or "").strip())
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await tg.send_text(update.message, "تم الإلغاء.")
    return ConversationHandler.END


def search_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CommandHandler("search", search_cmd),
            MessageHandler(filters.Regex("^🔎 بحث$"), search_cmd),
        ],
        states={AWAIT_QUERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_query)]},
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )


def register_handlers(app) -> None:
    pass
