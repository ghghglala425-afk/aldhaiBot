# -*- coding: utf-8 -*-
"""معالجات الإدارة: إحصاءات، بثّ، تفعيل التوليد."""
from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import CommandHandler, ContextTypes
from sqlalchemy import func, select

from core.config import settings
from core.db import SessionLocal
from core.logging import get_logger
from core.models import Course, Lab, Lesson, Progress, Submission, User
from app import tg

log = get_logger("bot.admin")


def is_admin(tg_id: int) -> bool:
    return tg_id in settings.admin_ids


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    async with SessionLocal() as s:
        users = await s.scalar(select(func.count()).select_from(User))
        lessons = await s.scalar(select(func.count()).select_from(Lesson))
        published = await s.scalar(select(func.count()).select_from(Lesson).where(Lesson.status == "published"))
        courses = await s.scalar(select(func.count()).select_from(Course))
        passed = await s.scalar(select(func.count()).select_from(Progress).where(Progress.status == "passed"))
        labs = await s.scalar(select(func.count()).select_from(Lab))
        solved = await s.scalar(select(func.count()).select_from(Submission).where(Submission.is_correct.is_(True)))
    await tg.send_text(update.message, 
        "📊 *إحصاءات المنصّة*\n"
        f"المستخدمون: {users}\n"
        f"الكورسات: {courses}\n"
        f"الدروس: {lessons} (منشورة {published})\n"
        f"دروس مكتملة: {passed}\n"
        f"المختبرات: {labs} (حُلّت {solved})",
        parse_mode=ParseMode.MARKDOWN,
    )


async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        return
    text = update.message.text.partition(" ")[2].strip()
    if not text:
        await tg.send_text(update.message, "الصيغة: /broadcast نص الرسالة")
        return
    async with SessionLocal() as s:
        ids = list((await s.execute(select(User.telegram_id).where(User.telegram_id.is_not(None)))).scalars().all())
    sent = 0
    for tg_id in ids:
        try:
            await context.bot.send_message(tg_id, f"📣 {text}")
            sent += 1
        except Exception:  # noqa: BLE001
            continue
    await tg.send_text(update.message, f"✅ أُرسل إلى {sent} مستخدم.")


async def build_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """إدارة توليد المحتوى: /build [all|retry|status|<lang>|warm <lang>]"""
    if not is_admin(update.effective_user.id):
        return
    from pipeline import jobs

    args = (update.message.text or "").partition(" ")[2].strip().split()
    sub = args[0].lower() if args else "status"

    if not settings.ai_configured and sub not in {"status"}:
        await tg.send_text(update.message, 
            "⚠️ لا يوجد مزوّد AI مضبوط — لا يمكن التوليد.\n"
            "فعّل AI_FREE_MODE=1 مع GEMINI_API_KEY/GROQ_API_KEY، "
            "أو اضبط AI_API_KEY لنقطة نهاية OpenAI-متوافقة."
        )
        return

    async with SessionLocal() as s:
        if sub in {"status", ""}:
            st = await jobs.queue_stats(s)
            await tg.send_text(update.message, 
                "🧱 *طابور التوليد*\n"
                f"منتظر: {st['queued']} · قيد التنفيذ: {st['running']}\n"
                f"مكتمل: {st['done']} · فشل: {st['failed']}\n"
                f"مخططات منجزة: {st['outline_done']} · دروس منجزة: {st['lesson_done']}\n\n"
                "الاستخدام:\n"
                "/build all — مخطط كل اللغات\n"
                "/build <lang> — مخطط لغة\n"
                "/build warm <lang> — تسخين أول الدروس\n"
                "/build retry — إعادة المحاولات الفاشلة",
                parse_mode=ParseMode.MARKDOWN,
            )
        elif sub == "all":
            n = await jobs.enqueue_all_languages(s)
            await tg.send_text(update.message, f"✅ أُدرج {n} مخطط لغة في الطابور.")
        elif sub == "retry":
            n = await jobs.retry_failed(s)
            await tg.send_text(update.message, f"♻️ أُعيد إدراج {n} مهمة فاشلة.")
        elif sub == "warm":
            lang = args[1] if len(args) > 1 else ""
            if not lang:
                await tg.send_text(update.message, "الصيغة: /build warm <lang>")
                return
            n = await jobs.enqueue_warm(s, lang)
            await tg.send_text(update.message, f"🔥 أُدرج تسخين {n} درسا للغة {lang}.")
        else:
            job = await jobs.enqueue_outline(s, sub)
            await tg.send_text(update.message, 
                f"✅ أُدرج مخطط اللغة {sub}." if job else f"⏳ مخطط {sub} قيد التنفيذ بالفعل."
            )


def register_handlers(app) -> None:
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CommandHandler("build", build_cmd))
    app.add_handler(CommandHandler("jobs", build_cmd))
