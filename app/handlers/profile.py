# -*- coding: utf-8 -*-
"""معالجات الملف: الدرس اليومي، الصدارة، الملاحظات، المرجعيات، الشهادات."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from sqlalchemy import select

from core.db import SessionLocal
from core.gamification import (
    add_note,
    list_bookmarks,
    list_notes,
    toggle_bookmark,
    user_rank,
    xp_leaderboard,
)
from core.learning import lesson_day, todays_daily
from core.logging import get_logger
from core.models import Certificate, Course, Lesson
from core.repo import get_user_by_telegram
from app import tg

log = get_logger("bot.profile")

ASK_NOTE = 200


async def _user(session, tg_id):
    return await get_user_by_telegram(session, tg_id)


async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with SessionLocal() as s:
        user = await _user(s, update.effective_user.id)
        if not user:
            await tg.send_text(update.effective_message, "سجّل دخولك أولا عبر /start.")
            return
        lesson = await todays_daily(s, user)
        if not lesson:
            await tg.send_text(update.effective_message, "🎉 أكملت كل الدروس المتاحة! تابع الإضافات قريبا.")
            return
        day = await lesson_day(s, lesson)
        head = "🎯 *درس اليوم*" + (f" — اليوم {day}" if day else "")
        await tg.send_text(update.effective_message, 
            f"{head}\n\n📖 {lesson.title}\n\n{(lesson.summary or '')[:200]}",
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


async def rank(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with SessionLocal() as s:
        user = await _user(s, update.effective_user.id)
        board = await xp_leaderboard(s, 10)
        my_rank = await user_rank(s, user) if user else None
    lines = ["🏆 *لوحة الصدارة*\n"]
    for r in board:
        lines.append(f"{r['rank']}. {r['name']} — {r['xp']} نقطة")
    if my_rank:
        lines.append(f"\n📍 ترتيبك: #{my_rank} ({user.xp} نقطة)")
    await tg.send_text(update.effective_message, "\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def notes_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with SessionLocal() as s:
        user = await _user(s, update.effective_user.id)
        if not user:
            await tg.send_text(update.effective_message, "سجّل دخولك أولا.")
            return
        rows = await list_notes(s, user.id, 15)
    if not rows:
        await tg.send_text(update.effective_message, "📝 لا توجد ملاحظات بعد. افتح درسا واضغط «ملاحظة».")
        return
    lines = ["📝 *ملاحظاتي*\n"]
    for n in rows:
        lines.append(f"• {n.text[:120]}")
    await tg.send_text(update.effective_message, "\n".join(lines)[:3900], parse_mode=ParseMode.MARKDOWN)


async def bookmarks_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with SessionLocal() as s:
        user = await _user(s, update.effective_user.id)
        if not user:
            await tg.send_text(update.effective_message, "سجّل دخولك أولا.")
            return
        rows = await list_bookmarks(s, user.id, 15)
    if not rows:
        await tg.send_text(update.effective_message, "🔖 لا توجد مرجعيات بعد.")
        return
    buttons = [[InlineKeyboardButton(f"🔖 {r['title']}", callback_data=f"lesson:{r['lesson_id']}")] for r in rows]
    await tg.send_text(update.effective_message, "🔖 *مرجعياتي*", parse_mode=ParseMode.MARKDOWN,
                                              reply_markup=InlineKeyboardMarkup(buttons))


async def certificates_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with SessionLocal() as s:
        user = await _user(s, update.effective_user.id)
        if not user:
            await tg.send_text(update.effective_message, "سجّل دخولك أولا.")
            return
        certs = list((await s.execute(
            select(Certificate).where(Certificate.user_id == user.id)
        )).scalars().all())
        courses = {
            c.id: c.title
            for c in (await s.execute(select(Course))).scalars().all()
        }
    if not certs:
        await tg.send_text(update.effective_message, "🎓 لا توجد شهادات بعد. أكمل كورسا كاملا.")
        return
    lines = ["🎓 *شهاداتي*\n"]
    for c in certs:
        lines.append(f"• {courses.get(c.course_id, 'كورس')} — `{c.code}`")
    await tg.send_text(update.effective_message, "\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def bookmark_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    lesson_id = int(q.data.split(":")[1])
    async with SessionLocal() as s:
        user = await _user(s, update.effective_user.id)
        if not user:
            await q.message.reply_text("سجّل دخولك أولا عبر /start.")
            return
        added = await toggle_bookmark(s, user.id, lesson_id)
    await q.message.reply_text("🔖 أُضيف إلى مرجعياتك." if added else "أُزيل من مرجعياتك.")


async def note_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    context.user_data["note_lesson"] = int(q.data.split(":")[1])
    await q.message.reply_text("📝 أرسل نص ملاحظتك (اكتب /cancel للإلغاء):")
    return ASK_NOTE


async def note_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lesson_id = context.user_data.pop("note_lesson", None)
    text = (update.message.text or "").strip()
    if not lesson_id or not text:
        await tg.send_text(update.message, "لا يمكن حفظ ملاحظة فارغة.")
        return ConversationHandler.END
    async with SessionLocal() as s:
        user = await _user(s, update.effective_user.id)
        if not user:
            await tg.send_text(update.message, "سجّل دخولك أولا عبر /start.")
            return ConversationHandler.END
        await add_note(s, user.id, lesson_id, text[:2000])
    await tg.send_text(update.message, "✅ حُفظت ملاحظتك.")
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("note_lesson", None)
    await tg.send_text(update.message, "تم الإلغاء.")
    return ConversationHandler.END


def notes_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(note_entry, pattern=r"^note:\d+$")],
        states={ASK_NOTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, note_save)]},
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
        per_message=True,
    )


def register_handlers(app) -> None:
    app.add_handler(CommandHandler("daily", daily))
    app.add_handler(CommandHandler("rank", rank))
    app.add_handler(CommandHandler("notes", notes_cmd))
    app.add_handler(CommandHandler("bookmarks", bookmarks_cmd))
    app.add_handler(CommandHandler("certificates", certificates_cmd))
    app.add_handler(CallbackQueryHandler(bookmark_toggle, pattern=r"^bm:\d+$"))
