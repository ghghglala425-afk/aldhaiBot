# -*- coding: utf-8 -*-
"""المُجدول: إرسال الدرس اليومي والتذكيرات (APScheduler عبر JobQueue)."""
from __future__ import annotations

import asyncio
import datetime as dt

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, ContextTypes

from core.db import SessionLocal
from core.learning import todays_daily
from core.logging import get_logger
from core.models import User
from core.repo import get_user_by_telegram
from sqlalchemy import select

log = get_logger("bot.scheduler")

DAILY_HOUR = 19  # بتوقيت الخادم
DAILY_MINUTE = 0


async def _send_daily(context: ContextTypes.DEFAULT_TYPE) -> None:
    async with SessionLocal() as s:
        ids = list(
            (await s.execute(select(User.telegram_id).where(User.telegram_id.is_not(None)))).scalars().all()
        )
    sent = 0
    for tg_id in ids:
        try:
            async with SessionLocal() as s:
                user = await get_user_by_telegram(s, tg_id)
                if not user:
                    continue
                lesson = await todays_daily(s, user)
            if not lesson:
                continue
            await context.bot.send_message(
                tg_id,
                f"🎯 *درس اليوم*\n\n📖 {lesson.title}\n{(lesson.summary or '')[:180]}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("▶️ افتح الدرس", callback_data=f"lesson:{lesson.id}")]]
                ),
            )
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:  # noqa: BLE001
            continue
    if sent:
        log.info("أُرسل الدرس اليومي إلى %s مستخدم.", sent)


async def remind_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "⏰ التذكيرات اليومية مفعّلة تلقائيا في الساعة "
        f"{DAILY_HOUR}:{DAILY_MINUTE:02d}. سنذكّرك بدرسك اليومي للحفاظ على سلسلتك 🔥"
    )


def setup_jobs(app: Application) -> None:
    jq = app.job_queue
    if jq is None:
        log.warning("JobQueue غير متاح — لن تعمل التذكيرات (ثبّت APScheduler).")
        return
    jq.run_daily(_send_daily, time=dt.time(hour=DAILY_HOUR, minute=DAILY_MINUTE))
    log.info("جدولة الدرس اليومي في %02d:%02d", DAILY_HOUR, DAILY_MINUTE)
