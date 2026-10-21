# -*- coding: utf-8 -*-
"""تمرين كود معزول لكل درس: يكتبه المستخدم ويُقيَّم تلقائيا داخل البيئة المعزولة."""
from __future__ import annotations

import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationHandlerStop,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from sqlalchemy import select

from app import tg
from app.handlers.common import esc
from core.db import SessionLocal
from core.learning import next_lesson_id
from core.logging import get_logger
from core.models import CodeSample, Lesson
from pipeline.sandbox_runner import run_code

log = get_logger("bot.exercise")

MAX_ATTEMPTS = 12


def _norm(text: str | None) -> str:
    """تطبيع الخرج للمقارنة: يحذف الفراغات الزائدة والسطرية في الأطراف."""
    lines = [ln.rstrip() for ln in (text or "").replace("\r\n", "\n").split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def _strip_fence(code: str) -> str:
    text = (code or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip("\n")


def _is_correct(expected: str, actual: str) -> bool:
    """مقارنة متسامحة: تتجاهل الفراغات الطرفية وحالة الأحرف."""
    if not expected:
        return False
    if actual.strip() == expected.strip():
        return True
    return actual.strip().lower() == expected.strip().lower()


async def _pick_reference(session, lesson_id: int) -> CodeSample | None:
    return await session.scalar(
        select(CodeSample)
        .where(CodeSample.lesson_id == lesson_id)
        .order_by(CodeSample.order_index, CodeSample.id)
    )


async def _start(message, context: ContextTypes.DEFAULT_TYPE, lesson_id: int) -> None:
    async with SessionLocal() as s:
        lesson = await s.get(Lesson, lesson_id)
        code = await _pick_reference(s, lesson_id)
    if not lesson:
        await tg.send_text(message, "الدرس غير موجود.")
        return
    if not code:
        await tg.send_text(message, "🧪 لا يوجد مثال كود لهذا الدرس بعد — سيُضاف مع اكتمال المحتوى.")
        return

    expected = _norm(code.expected_output)
    if not expected:
        probe = await run_code(code.language or "python", code.code, exec_enabled=True)
        if probe.status == "ok":
            expected = _norm(probe.stdout)
        elif probe.status == "skipped":
            await tg.send_text(
                message,
                "⚠️ بيئة التنفيذ المعزولة غير متاحة على الخادم الآن "
                "(فعّل Docker أو SANDBOX_LOCAL=1). يمكنك مراجعة الحل فقط.",
            )

    context.user_data["exercise"] = {
        "lesson_id": lesson_id,
        "language": code.language or "python",
        "expected": expected,
        "ref_code": code.code,
        "ref_title": code.title,
        "hint": (code.explanation or "")[:600],
        "attempts": 0,
        "started": time.monotonic(),
    }

    hint = (code.explanation or code.title or "").strip()
    body = (
        f"🧪 <b>تمرين الدرس</b> — {esc(lesson.title)}\n"
        f"اللغة: <code>{esc(code.language or 'python')}</code>\n\n"
        f"<b>المهمة:</b> اكتب كودا يعطي نفس الخرج المطلوب.\n"
    )
    if hint:
        body += f"<i>{esc(hint[:500])}</i>\n"
    if expected:
        body += f"\n<b>الخرج المتوقع:</b>\n<pre>{esc(expected[:1200])}</pre>\n"
    else:
        body += (
            "\n⚠️ <i>تعذّر استخراج الخرج المرجعي لهذا المثال، لذا سيكون التقييم "
            "«كود يعمل بلا أخطاء ويطبع خرجاً» بدلا من مطابقة نصية.</i>\n"
        )
    body += (
        "\nأرسل الكود الآن في رسالة (بلا شرح). "
        "أو اضغط «🛑 إنهاء» للخروج."
    )
    await tg.send_text(
        message,
        body,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("👀 أظهر الحل", callback_data=f"exsol:{lesson_id}"),
                    InlineKeyboardButton("🛑 إنهاء", callback_data="exstop"),
                ]
            ]
        ),
    )


async def start_exercise(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer("جهّزت التمرين 🧪")
    lesson_id = int(q.data.split(":")[1])
    await _start(q.message, context, lesson_id)


async def reveal_solution(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    lesson_id = int(q.data.split(":")[1])
    async with SessionLocal() as s:
        code = await _pick_reference(s, lesson_id)
    if not code:
        await tg.send_text(q.message, "لا يوجد حل مرجعي لهذا الدرس.")
        return
    await tg.send_text(
        q.message,
        f"👀 <b>الحل المرجعي:</b> {esc(code.title)}\n"
        f"<pre>{esc(code.code[:3000])}</pre>\n"
        "<i>اقرأه ثم أعد كتابته بنفسك — هذا ما يثبّت المهارة.</i>",
        parse_mode=ParseMode.HTML,
    )


async def stop_exercise(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    context.user_data.pop("exercise", None)
    await tg.send_text(q.message, "🛑 أنهيت التمرين. تابعه لاحقا من «📎 ملحقات الدرس».")


async def submit_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يستقبل كود المستخدم ويقيّمه تلقائيا. يعمل فقط أثناء تمرين نشط."""
    st = context.user_data.get("exercise")
    if not st:
        return
    text = _strip_fence(update.message.text or "")
    if not text.strip():
        return
    # لا تلتقط أزرار القائمة السفلية كأنها كود.
    from app.keyboards import MENU_TEXTS

    if text.strip() in MENU_TEXTS:
        return
    st["attempts"] = int(st.get("attempts") or 0) + 1
    if st["attempts"] > MAX_ATTEMPTS:
        context.user_data.pop("exercise", None)
        await tg.send_text(update.effective_message, "انتهت محاولات التمرين. ابدأه مجددا لاحقا.")
        raise ApplicationHandlerStop

    msg = await update.effective_message.reply_text("⏳ أُشغّل كودك في البيئة المعزولة…")
    started = time.monotonic()
    try:
        res = await run_code(st["language"], text, exec_enabled=True)
    except Exception as e:  # noqa: BLE001
        log.exception("فشل تشغيل تمرين الدرس #%s", st.get("lesson_id"))
        context.user_data.pop("exercise", None)
        await msg.edit_text(f"❌ تعذّر تشغيل الكود: {esc(str(e)[:200])}", parse_mode=ParseMode.HTML)
        raise ApplicationHandlerStop
    elapsed = time.monotonic() - started

    expected = st.get("expected") or ""
    actual = _norm(res.stdout)
    if expected:
        passed = _is_correct(expected, actual)
    else:
        # لا خرج مرجعي متاح: التقييم بنجاح التشغيل ووجود خرج فعلي.
        passed = res.status == "ok" and bool(actual.strip())

    if res.status == "skipped":
        context.user_data.pop("exercise", None)
        await msg.edit_text(
            "⚠️ <b>بيئة التنفيذ غير متاحة الآن</b>\n"
            f"{esc(res.detail or '')}\n\n"
            "يمكنك مراجعة الحل المرجعي ثم إعادة المحاولة لاحقا.",
            parse_mode=ParseMode.HTML,
        )
        raise ApplicationHandlerStop

    if passed:
        context.user_data.pop("exercise", None)
        lesson_id = st["lesson_id"]
        async with SessionLocal() as s:
            lesson = await s.get(Lesson, lesson_id)
            nxt = await next_lesson_id(s, lesson) if lesson else None
        rows = [[InlineKeyboardButton("👀 الحل المرجعي", callback_data=f"exsol:{lesson_id}")]]
        if nxt:
            rows.insert(0, [InlineKeyboardButton("➡️ الدرس التالي", callback_data=f"lesson:{nxt}")])
        body = (
            "✅ <b>أحسنت! كودك صحيح</b>\n"
            f"الزمن: {elapsed:.1f}s · المحرّك: <code>{esc(res.engine or '—')}</code>\n"
        )
        if actual:
            body += f"\n<b>خرجك:</b>\n<pre>{esc(actual[:1200])}</pre>"
        await msg.edit_text(
            body,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(rows),
        )
        raise ApplicationHandlerStop

    # فشل: أظهر الفرق وسجّل المحاولة.
    body = (
        "❌ <b>ليس بعد</b> — الخرج لا يطابق المتوقع.\n"
        f"الزمن: {elapsed:.1f}s · المحرّك: <code>{esc(res.engine or '—')}</code>\n"
    )
    if res.detail:
        body += f"ملاحظة: {esc(res.detail)}\n"
    if expected:
        body += f"\n<b>المتوقع:</b>\n<pre>{esc(expected[:900])}</pre>"
    else:
        body += (
            "\n<i>لا يوجد خرج مرجعي — تأكد أن الكود يعمل بلا أخطاء ويطبع خرجاً.</i>\n"
        )
    if actual:
        body += f"\n<b>خرجك:</b>\n<pre>{esc(actual[:900])}</pre>"
    if res.stderr:
        body += f"\n<b>أخطاء:</b>\n<pre>{esc(res.stderr[:900])}</pre>"
    body += "\n<i>عدّل الكود وأرسله مرة أخرى، أو اضغط «👀 أظهر الحل».</i>"
    if st.get("hint") and st["attempts"] >= 2:
        body += f"\n<b>💡 تلميح:</b> {esc(st['hint'][:400])}"
    body += f"\n<b>🔁 المحاولة:</b> {st['attempts']}/{MAX_ATTEMPTS}"
    lesson_id = st["lesson_id"]
    await msg.edit_text(
        body[:3900],
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("👀 أظهر الحل", callback_data=f"exsol:{lesson_id}")],
                [InlineKeyboardButton("🛑 إنهاء", callback_data="exstop")],
            ]
        ),
    )
    raise ApplicationHandlerStop


async def auto_start_after_quiz(message, context: ContextTypes.DEFAULT_TYPE, lesson_id: int) -> None:
    """ينتقل تلقائيا إلى تمرين البيئة المعزولة بعد اجتياز الاختبار."""
    await _start(message, context, lesson_id)


def register_handlers(app) -> None:
    app.add_handler(CallbackQueryHandler(start_exercise, pattern=r"^exs:\d+$"))
    app.add_handler(CallbackQueryHandler(reveal_solution, pattern=r"^exsol:\d+$"))
    app.add_handler(CallbackQueryHandler(stop_exercise, pattern=r"^exstop$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, submit_code))


__all__ = ["register_handlers", "auto_start_after_quiz", "start_exercise"]
