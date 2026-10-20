# -*- coding: utf-8 -*-
"""المساعد الذكي: أسئلة حرة (/ask) + شرح درس/كود بالذكاء الاصطناعي."""
from __future__ import annotations

import asyncio
import re

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from sqlalchemy import select

from app.handlers.common import ai_error_text, animate_status, reply_long
from core.config import settings
from core.db import SessionLocal
from core.logging import get_logger
from core.models import CodeSample, Lesson
from pipeline.ai import chat_text
from app import tg

log = get_logger("bot.assistant")

AWAIT_Q = 500

# مهلة قصيرة نسبيا حتى لا يبقى المستخدم أمام «أفكّر…» بلا نهاية.
ANSWER_TIMEOUT = 90.0
DEEP_TIMEOUT = 150.0

TUTOR_SYSTEM = (
    "أنت مدرّب برمجة وأمن سيبراني عربي خبير، تشرح بوضوح وعمق وبأسلوب عالمي.\n"
    "اكتب بالعربية الفصحى المبسطة، وبنص منظّم بلا رموز Markdown معقّدة:\n"
    "• مقدمة قصيرة (2-3 أسطر) تحدّد الفكرة الأساسية.\n"
    "• شرح خطوة بخطوة مرقّم، مع سبب كل خطوة.\n"
    "• مثال عملي كامل قابل للتشغيل، ثم شرح كل جزء منه.\n"
    "• أخطاء شائعة وكيف تتجنّبها.\n"
    "• ملاحظات أمان عند الحاجة.\n"
    "• خلاصة من 3 نقاط.\n"
    "كن مفصّلا (600-1000 كلمة) بلا حشو ولا تكرار، وضع المصطلح الإنجليزي بين قوسين "
    "عند أول ظهور له. إن طُلب كود فاجعله كاملا وجاهزا للنسخ."
)


def _error_text(err: Exception) -> str:
    return "⚠️ " + ai_error_text(err)


def _plain_md(text: str) -> str:
    """يبسّط Markdown ليُرسل كنص عادي مقروء في تيليجرام."""
    out = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text or "")
    out = out.replace("**", "").replace("`", "").replace("&gt;", ">")
    return out.strip()


def _lesson_fallback(lesson: Lesson, codes: list[CodeSample]) -> str:
    """شرح محلي من محتوى الدرس حين يتعذّر الوصول للذكاء الاصطناعي."""
    parts = [f"📘 شرح الدرس (نسخة محلية): {lesson.title}"]
    if lesson.summary:
        parts.append(f"\nالملخص:\n{lesson.summary}")
    if lesson.objectives:
        parts.append("\nالأهداف:")
        parts.extend(f"• {o}" for o in lesson.objectives)
    if lesson.content_md:
        parts.append("\n" + _plain_md(lesson.content_md))
    if lesson.key_points:
        parts.append("\nنقاط المفتاح:")
        parts.extend(f"• {k}" for k in lesson.key_points)
    if lesson.memory_hook:
        parts.append(f"\n🧠 خطّاف الذاكرة: {lesson.memory_hook}")
    for i, c in enumerate(codes, start=1):
        parts.append(f"\n💻 مثال {i}: {c.title}")
        if c.explanation:
            parts.append(c.explanation)
        if c.gotchas:
            parts.append("أخطاء شائعة:")
            parts.extend(f"• {g}" for g in c.gotchas)
        if c.security_notes:
            parts.append("أمان:")
            parts.extend(f"• {g}" for g in c.security_notes)
    return "\n".join(parts)


async def _run_ai(
    message, base: str, note: str, prompt: str, *, timeout: float
) -> str | None:
    """ينفّذ نداء AI مع مؤشر انتظار متجدد، ويُرجع None (بعد إظهار الخطأ) عند الفشل."""
    msg = await message.reply_text(base)
    stop = asyncio.Event()
    ticker = asyncio.create_task(animate_status(msg, stop, base, note=note))
    try:
        answer = await chat_text(
            TUTOR_SYSTEM,
            prompt,
            max_tokens=min(settings.AI_MAX_TOKENS, 8192),
            timeout=timeout,
            max_retries=1,
        )
        try:
            await msg.delete()
        except Exception:  # noqa: BLE001
            pass
        return answer
    except Exception as e:  # noqa: BLE001
        log.warning("تعذّر نداء المساعد: %s", e)
        try:
            await msg.edit_text(_error_text(e))
        except Exception:  # noqa: BLE001
            pass
        return None
    finally:
        stop.set()
        ticker.cancel()
        try:
            await ticker
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001
            pass


async def _answer(update: Update, question: str) -> None:
    from app import ratelimit

    if not await ratelimit.guard(update, "ask"):
        return
    if not settings.ai_configured:
        await tg.send_text(update.effective_message, "🤖 المساعد الذكي يحتاج ضبط AI_API_KEY.")
        return
    answer = await _run_ai(
        update.effective_message,
        "🤖 أفكّر وأجهّز إجابة مفصّلة…",
        "أكتب شرحا مفصّلا…",
        question,
        timeout=ANSWER_TIMEOUT,
    )
    if answer is None:
        return
    answer = answer.strip()
    if not answer:
        await tg.send_text(update.effective_message, "⚠️ وصل رد فارغ من المزوّد. أعد المحاولة.")
        return
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
    await q.answer("أحضّر شرحا أعمق…")
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
    body = (lesson.content_md or "")[:4000]
    samples = "\n\n".join(f"# {c.title}\n{c.code[:600]}" for c in codes[:5])
    prompt = (
        "اشرح هذا الدرس كأنك مدرّس خاص للمستخدم، بشرح أعمق وأبسط من النص الأصلي:\n"
        f"العنوان: {lesson.title}\n"
        f"الملخص: {lesson.summary or ''}\n"
        f"الأهداف: {'؛ '.join(lesson.objectives or [])}\n\n"
        f"المحتوى:\n{body}\n\n"
        f"أمثلة الكود:\n{samples}\n\n"
        "المطلوب: أعد شرح الفكرة من الصفر، فكّك كل مثال سطرا بسطر، أضف مثالا إضافيا "
        "مختلفا، واذكر 3 أخطاء يرتكبها المبتدئون وكيف يتجنّبونها، ثم خلاصة عملية."
    )
    answer = await _run_ai(
        q.message,
        "🤖 أشرح الدرس بعمق…",
        "أعيد بناء الشرح وأضيف أمثلة…",
        prompt,
        timeout=DEEP_TIMEOUT,
    )
    if answer is None:
        await reply_long(q.message, _lesson_fallback(lesson, codes))
        return
    await reply_long(q.message, answer.strip())


async def explain_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer("أشرح الكود بعمق…")
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
        "اشرح الكود التالي شرحا تعليميا كاملا:\n"
        f"اللغة: {c.language}\nالعنوان: {c.title}\n\n{c.code}\n\n"
        "المطلوب: 1) ماذا يحل هذا الكود؟ 2) شرح كل سطر أو مجموعة أسطر مرتبطة. "
        "3) الخرج المتوقع. 4) كيف تجعله أفضل وأكثر أمانا. 5) نسخة معدّلة محسّنة من الكود."
    )
    answer = await _run_ai(
        q.message,
        "🤖 أشرح الكود سطرا بسطر…",
        "أحلّل الكود وأجهّز نسخة محسّنة…",
        prompt,
        timeout=DEEP_TIMEOUT,
    )
    if answer is not None:
        await reply_long(q.message, answer.strip())
        return
    parts = [f"💡 شرح الكود (نسخة محلية): {c.title}"]
    if c.explanation:
        parts.append(c.explanation)
    if c.gotchas:
        parts.append("\nأخطاء شائعة:")
        parts.extend(f"• {g}" for g in c.gotchas)
    if c.security_notes:
        parts.append("\nملاحظات أمان:")
        parts.extend(f"• {g}" for g in c.security_notes)
    await reply_long(q.message, "\n".join(parts))


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
