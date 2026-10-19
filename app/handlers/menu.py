# -*- coding: utf-8 -*-
"""موجّه أزرار القائمة السفلية (يعمل في المجموعة 0).

الأزرار التفاعلية (بحث/مساعد/تشغيل كود/الأدوات) لها محادثات خاصة في مجموعات لاحقة،
فلا نلتقطها هنا حتى تصل إلى معالجها الصحيح.
"""
from __future__ import annotations

import re

from telegram import Update
from telegram.ext import CallbackQueryHandler, MessageHandler, filters

from app import keyboards as kb
from app.handlers import languages, learn, paths, profile, start
from core.logging import get_logger

log = get_logger("bot.menu")

IMMEDIATE = {
    kb.MENU_COURSES: learn.courses_cmd,
    kb.MENU_LANGUAGES: languages.languages_cmd,
    kb.MENU_PATHS: paths.paths_cmd,
    kb.MENU_DAILY: profile.daily,
    kb.MENU_RANK: profile.rank,
    kb.MENU_ACCOUNT: start.my_account,
}


def _pattern() -> str:
    return "^(" + "|".join(re.escape(t) for t in IMMEDIATE) + ")$"


async def reply_menu(update: Update, context) -> None:
    text = (update.message.text or "").strip()
    handler = IMMEDIATE.get(text)
    if handler:
        await handler(update, context)


async def noop(update: Update, context) -> None:
    await update.callback_query.answer()


def register_handlers(app) -> None:
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND & filters.Regex(_pattern()), reply_menu)
    )
    app.add_handler(CallbackQueryHandler(noop, pattern=r"^noop$"))
