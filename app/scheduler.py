# -*- coding: utf-8 -*-
"""المُجدول: إرسال الدرس اليومي والتذكيرات (APScheduler عبر JobQueue)."""
from __future__ import annotations

import asyncio
import datetime as dt
import html

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, ContextTypes

from core.config import settings
from core.db import SessionLocal
from core.learning import lesson_day, todays_daily
from core.logging import get_logger
from core.models import Lesson, User
from core.reminders import current_lesson, mark_reminded, pending_reminders
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
            day = await lesson_day(s, lesson)
            head = "🎯 *درس اليوم*" + (f" — اليوم {day}" if day else "")
            await context.bot.send_message(
                tg_id,
                f"{head}\n\n📖 {lesson.title}\n{(lesson.summary or '')[:180]}",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("▶️ افتح الدرس", callback_data=f"lesson:{lesson.id}")],
                        [
                            InlineKeyboardButton("🧪 تمرين معزول", callback_data=f"exs:{lesson.id}"),
                            InlineKeyboardButton("📎 الملحقات", callback_data=f"latt:{lesson.id}"),
                        ],
                    ]
                ),
            )
            sent += 1
            await asyncio.sleep(0.05)
        except Exception:  # noqa: BLE001
            continue
    if sent:
        log.info("أُرسل الدرس اليومي إلى %s مستخدم.", sent)


async def _send_progress_reminders(context: ContextTypes.DEFAULT_TYPE) -> None:
    """يذكّر من توقف عن مساره 23 ساعة (مرة كل 23 ساعة كحد أقصى)."""
    try:
        async with SessionLocal() as s:
            due = await pending_reminders(s)
    except Exception as e:  # noqa: BLE001
        log.warning("تعذّر فحص التذكيرات: %s", e)
        return

    sent = 0
    for item in due:
        user = item["user"]
        lesson = item["lesson"]
        idle = item["idle_hours"]
        try:
            async with SessionLocal() as s:
                fresh = await s.get(Lesson, lesson.id)
                day = await lesson_day(s, fresh) if fresh else None
                title = fresh.title if fresh else lesson.title

            lines = [
                "⏰ <b>تذكير دراسي</b>",
                "",
                f"مرّت <b>{idle} ساعة</b> بلا تعلّم — مسارك ينتظرك:",
                f"📖 <b>{html.escape(title)}</b>",
            ]
            if day:
                lines.append(f"📅 اليوم {day} من المسار")
            lines.append("")
            lines.append(
                "<i>أكمل الدرس ثم اجتز الاختبار — "
                f"{settings.QUIZ_PASS_PERCENT}% تكفي لفتح الدرس التالي تلقائيا.</i>"
            )
            await context.bot.send_message(
                user.telegram_id,
                "\n".join(lines),
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "▶️ أكمل الدرس", callback_data=f"lesson:{lesson.id}"
                            )
                        ],
                        [
                            InlineKeyboardButton(
                                "🧠 اختبار الدرس", callback_data=f"qz_start:{lesson.id}"
                            )
                        ],
                    ]
                ),
            )
            async with SessionLocal() as s:
                await mark_reminded(s, user.id)
            sent += 1
            await asyncio.sleep(0.05)
        except Exception as e:  # noqa: BLE001
            log.debug("تعذّر إرسال تذكير للمستخدم %s: %s", user.id, e)
    if sent:
        log.info("أُرسلت %s تذكيرات دراسية.", sent)


async def remind_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يعرض الدرس الحالي في المسار ويتيح استئنافه فورا."""
    tg_id = update.effective_user.id if update.effective_user else None
    lesson = None
    day = None
    if tg_id:
        try:
            async with SessionLocal() as s:
                user = await get_user_by_telegram(s, tg_id)
                if user:
                    lesson, _course_id = await current_lesson(s, user.id)
                    if lesson:
                        day = await lesson_day(s, lesson)
        except Exception as e:  # noqa: BLE001
            log.debug("تعذّر جلب درس المستخدم: %s", e)

    if lesson is None:
        await update.message.reply_text(
            "✅ لا يوجد درس متبقٍ في مسارك الحالي.\n"
            "اختر مسارا جديدا بالأمر /courses وسنذكّرك كل 23 ساعة إن توقفت."
        )
        return

    head = "⏰ <b>تذكير دراسي</b>"
    lines = [head, "", "📖 <b>" + html.escape(lesson.title) + "</b>"]
    if day:
        lines.append(f"📅 اليوم {day} من المسار")
    lines.append("")
    lines.append(
        f"<i>سنذكّرك تلقائيا كل {settings.REMINDER_IDLE_HOURS} ساعة إذا توقفت. "
        f"اجتز الاختبار بنسبة {settings.QUIZ_PASS_PERCENT}% لفتح الدرس التالي.</i>"
    )
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("▶️ أكمل الدرس", callback_data=f"lesson:{lesson.id}")],
                [InlineKeyboardButton("🧠 اختبار الدرس", callback_data=f"qz_start:{lesson.id}")],
            ]
        ),
    )


def setup_jobs(app: Application) -> None:
    jq = app.job_queue
    if jq is None:
        log.warning("JobQueue غير متاح — لن تعمل التذكيرات (ثبّت APScheduler).")
        return
    jq.run_daily(_send_daily, time=dt.time(hour=DAILY_HOUR, minute=DAILY_MINUTE))
    log.info("جدولة الدرس اليومي في %02d:%02d", DAILY_HOUR, DAILY_MINUTE)

    # تذكير من توقف عن مساره: فحص دوري، والإرسال الفعلي كل 23 ساعة خمول.
    minutes = max(10, int(settings.REMINDER_CHECK_MINUTES))
    jq.run_repeating(
        _send_progress_reminders,
        interval=dt.timedelta(minutes=minutes),
        first=dt.timedelta(minutes=3),
    )
    log.info(
        "جدولة التذكيرات الدراسية كل %s دقيقة (خمول %s ساعة)",
        minutes,
        settings.REMINDER_IDLE_HOURS,
    )
