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
            # كل شيء داخل الجلسة: استخدامها بعد الإغلاق يفتح اتصالا لا يُغلق
            # (تحذير garbage collector عن connections غير معادة للمجمّع).
            async with SessionLocal() as s:
                user = await get_user_by_telegram(s, tg_id)
                if not user:
                    continue
                lesson = await todays_daily(s, user)
                if not lesson:
                    continue
                day = await lesson_day(s, lesson)
                lesson_id = lesson.id
                lesson_title = html.escape(lesson.title)
                lesson_summary = html.escape((lesson.summary or "")[:180])
            head = "🎯 <b>درس اليوم</b>" + (f" — اليوم {day}" if day else "")
            await context.bot.send_message(
                tg_id,
                f"{head}\n\n📖 <b>{lesson_title}</b>\n"
                f"{lesson_summary}\n\n"
                f"<i>اجتز الاختبار بـ {settings.QUIZ_PASS_PERCENT}% لفتح التالي — "
                "ويمكنك دراسة أكثر من 10 دروس اليوم.</i>",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("▶️ افتح الدرس", callback_data=f"lesson:{lesson_id}")],
                        [
                            InlineKeyboardButton("🧠 الاختبار", callback_data=f"qz_start:{lesson_id}"),
                            InlineKeyboardButton("📚 خطة دروسي", callback_data="dplan:0"),
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


async def _send_backup(context: ContextTypes.DEFAULT_TYPE) -> None:
    """نسخة احتياطية يومية تُرسل إلى المشرفين كملف (حفظ خارج الخادم)."""
    if not settings.admin_ids:
        return
    import io

    from pipeline.backup import backup_filename, dump_user_data

    try:
        blob, counts = await dump_user_data()
    except Exception as e:  # noqa: BLE001
        log.exception("تعذّر إنشاء النسخة الاحتياطية اليومية: %s", e)
        return

    total = sum(counts.values())
    caption = (
        "💾 <b>نسخة احتياطية يومية</b>\n"
        f"الصفوف: {total} · الحجم: {len(blob) / 1024:.1f} KB\n"
        f"مستخدمون {counts.get('users', 0)} · تقدّم {counts.get('progress', 0)}"
    )
    sent = 0
    for admin_id in settings.admin_ids:
        buf = io.BytesIO(blob)
        buf.name = backup_filename()
        try:
            await context.bot.send_document(
                chat_id=admin_id,
                document=buf,
                filename=buf.name,
                caption=caption,
                parse_mode=ParseMode.HTML,
            )
            sent += 1
        except Exception as e:  # noqa: BLE001
            log.warning("تعذّر إرسال النسخة الاحتياطية إلى %s: %s", admin_id, e)
    log.info("أُرسلت النسخة الاحتياطية إلى %s مشرف.", sent)


async def _refresh_prebuild(context: ContextTypes.DEFAULT_TYPE) -> None:
    """يعيد ملء دروس اللغات الشائعة بلا تكرار (Top-up دوري)."""
    if not settings.ai_configured:
        return
    from pipeline import jobs

    try:
        stats = await jobs.warm_popular()
    except Exception as e:  # noqa: BLE001
        log.warning("تعذّر تسخين اللغات الشائعة: %s", e)
        return
    queued = sum(v for v in stats.values() if v > 0)
    if queued:
        log.info("تسخين دوري: %s درسا جديدا (%s).", queued, stats)


async def _send_weekly_report(context: ContextTypes.DEFAULT_TYPE) -> None:
    """يُرسل تقرير التشغيل واستهلاك الذكاء الاصطناعي إلى المشرفين أسبوعيا."""
    if not settings.admin_ids:
        return
    from pipeline.report import build_weekly_report, render_report

    try:
        data = await build_weekly_report()
        text = render_report(data)
    except Exception as e:  # noqa: BLE001
        log.exception("تعذّر إنشاء التقرير الأسبوعي: %s", e)
        return
    for admin_id in settings.admin_ids:
        try:
            await context.bot.send_message(
                admin_id, text, parse_mode=ParseMode.HTML
            )
        except Exception as e:  # noqa: BLE001
            log.warning("تعذّر إرسال التقرير إلى %s: %s", admin_id, e)


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

    if settings.BACKUP_ENABLED and settings.admin_ids:
        jq.run_daily(
            _send_backup,
            time=dt.time(hour=settings.BACKUP_HOUR, minute=settings.BACKUP_MINUTE),
        )
        log.info(
            "جدولة النسخ الاحتياطي اليومي في %02d:%02d UTC",
            settings.BACKUP_HOUR,
            settings.BACKUP_MINUTE,
        )

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

    if settings.PREBUILD_ENABLED and settings.ai_configured:
        refresh = max(15, int(settings.PREBUILD_REFRESH_MINUTES))
        jq.run_repeating(
            _refresh_prebuild,
            interval=dt.timedelta(minutes=refresh),
            first=dt.timedelta(minutes=5),
        )
        log.info(
            "جدولة تسخين اللغات الشائعة كل %s دقيقة: %s",
            refresh,
            ", ".join(settings.prebuild_langs),
        )

    if settings.REPORT_ENABLED and settings.admin_ids:
        jq.run_daily(
            _send_weekly_report,
            time=dt.time(hour=settings.REPORT_HOUR, minute=settings.REPORT_MINUTE),
            days=(settings.REPORT_WEEKDAY % 7,),
        )
        log.info(
            "جدولة التقرير الأسبوعي يوم %s في %02d:%02d UTC",
            settings.REPORT_WEEKDAY,
            settings.REPORT_HOUR,
            settings.REPORT_MINUTE,
        )
