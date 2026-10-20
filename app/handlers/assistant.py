# -*- coding: utf-8 -*-
"""المساعد الذكي: أسئلة حرة (/ask) + شرح درس/كود بالذكاء الاصطناعي."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from sqlalchemy import select

from app.handlers.common import reply_long
from core.config import settings
from core.db import SessionLocal
from core.logging import get_logger
from core.models import CodeSample, Lesson
from pipeline.ai import AIError, chat_text
from app import tg

log = get_logger("bot.assistant")

AWAIT_Q = 500

TUTOR_SYSTEM = (
    "أنت مدرّب برمجة وأمن سيبراني عربي خبير. أجب بالعربية الفصحى المبسطة، "
    "بدقة وعمليا، مع أمثلة قصيرة عند الحاجة، وبدون حشو."
)


async def _answer(update: Update, question: str) -> None:
    from app import ratelimit

    if not await ratelimit.guard(update, "ask"):
        return
    if not settings.ai_configured:
        await tg.send_text(update.effective_message, "🤖 المساعد الذكي يحتاج ضبط AI_API_KEY.")
        return
    thinking = await tg.send_text(update.effective_message, "🤖 أفكّر…")
    try:
        answer = await chat_text(TUTOR_SYSTEM, question)
    except AIError as e:
        await thinking.edit_text(f"⚠️ تعذّر الحصول على رد: {e}")
        return
    try:
        await thinking.delete()
    except Exception:  # noqa: BLE001
        pass
    await reply_long(update.effective_message, f"🤖 {answer}")


async def ask_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    question = (update.message.text or "").partition(" ")[2].strip()
    if question:
        await _answer(update, question)
        return ConversationHandler.END
    await tg.send_text(update.message, "🤖 أرسل سؤالك الآن (اكتب /cancel للإلغاء):")
    return AWAIT_Q


async def got_question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await _answer(update, (update.message.text or "").strip())
    return ConversationHandler.END


async def explain_lesson(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer("أحضّر الشرح…")
    lesson_id = int(q.data.split(":")[1])
    async with SessionLocal() as s:
        lesson = await s.get(Lesson, lesson_id)
        codes = list(
            (await s.execute(
                select(CodeSample).where(CodeSample.lesson_id == lesson_id).order_by(CodeSample.order_index)
            )).scalars().all()
        )
    if not lesson:
        await q.message.reply_text("الدرس غير موجود.")
        return
    if not settings.ai_configured:
        await q.message.reply_text("🤖 الشرح يحتاج ضبط AI_API_KEY.")
        return
    body = (lesson.content_md or "")[:2500]
    samples = "\n\n".join(f"# {c.title}\n{c.code[:400]}" for c in codes[:4])
    prompt = (
        f"اشرح هذا الدرس ببساطة وبعمق مناسب:\nالعنوان: {lesson.title}\n"
        f"الملخص: {lesson.summary or ''}\n\nالمحتوى:\n{body}\n\nأمثلة:\n{samples}"
    )
    msg = await q.message.reply_text("🤖 أشرح الدرس…")
    try:
        answer = await chat_text(TUTOR_SYSTEM, prompt)
    except AIError as e:
        await msg.edit_text(f"⚠️ تعذّر الشرح: {e}")
        return
    await msg.edit_text("📘 الشرح جاهز 👇")
    await reply_long(q.message, answer)


async def explain_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer("أشرح الكود…")
    code_id = int(q.data.split(":")[1])
    async with SessionLocal() as s:
        c = await s.get(CodeSample, code_id)
    if not c:
        await q.message.reply_text("الكود غير موجود.")
        return
    if not settings.ai_configured:
        await q.message.reply_text("🤖 الشرح يحتاج ضبط AI_API_KEY.")
        return
    prompt = (
        f"اشرح الكود التالي سطرا بسطر وبيّن فائدته وربما مخاطره الأمنية:\n"
        f"اللغة: {c.language}\nالعنوان: {c.title}\n\n{c.code}"
    )
    msg = await q.message.reply_text("🤖 أشرح الكود…")
    try:
        answer = await chat_text(TUTOR_SYSTEM, prompt)
    except AIError as e:
        await msg.edit_text(f"⚠️ تعذّر الشرح: {e}")
        return
    await msg.edit_text("💡 الشرح جاهز 👇")
    await reply_long(q.message, answer)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await tg.send_text(update.message, "تم الإلغاء.")
    return ConversationHandler.END


def ask_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CommandHandler("ask", ask_cmd),
            MessageHandler(filters.Regex("^🤖 المساعد$"), ask_cmd),
        ],
        states={AWAIT_Q: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_question)]},
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )


def register_handlers(app) -> None:
    app.add_handler(CallbackQueryHandler(explain_lesson, pattern=r"^aex:\d+$"))
    app.add_handler(CallbackQueryHandler(explain_code, pattern=r"^acode:\d+$"))
