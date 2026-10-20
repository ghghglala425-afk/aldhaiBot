# -*- coding: utf-8 -*-
"""سؤال وجواب لكل درس (نقاش مبنى على جدول Discussion)."""
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
from core.logging import get_logger
from core.models import Discussion, Lesson, User
from app import tg

log = get_logger("bot.qa")

AWAIT_BODY = 900
MAX_ITEMS = 8


async def _render(update: Update, context: ContextTypes.DEFAULT_TYPE, lesson_id: int) -> None:
    async with SessionLocal() as s:
        lesson = await s.get(Lesson, lesson_id)
        roots = list((await s.execute(
            select(Discussion).where(
                Discussion.lesson_id == lesson_id, Discussion.parent_id.is_(None)
            ).order_by(Discussion.id.desc()).limit(MAX_ITEMS)
        )).scalars().all())
        replies: dict[int, int] = {}
        for r in roots:
            cnt = await s.scalar(
                select(Discussion.id).where(Discussion.parent_id == r.id).limit(1)
            )
            replies[r.id] = 1 if cnt else 0
        names: dict[int, str] = {}
        for uid in {r.user_id for r in roots}:
            u = await s.get(User, uid)
            if u:
                names[uid] = u.username or (u.email or "مستخدم")[:14]
    if not lesson:
        await tg.send_text(update.effective_message, "الدرس غير موجود.")
        return
    lines = [f"💬 *نقاش الدرس:* {lesson.title}", ""]
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton("✍️ اطرح سؤالا", callback_data=f"qaask:{lesson_id}")]
    ]
    if not roots:
        lines.append("لا توجد أسئلة بعد — كن أول من يسأل!")
    for r in roots:
        who = names.get(r.user_id, "مستخدم")
        tag = f"  (↩️ {replies[r.id]})" if replies.get(r.id) else ""
        lines.append(f"❓ *{who}*{tag}\n{r.body[:300]}")
        rows.append([InlineKeyboardButton(f"↩️ اجِب: {r.body[:34]}", callback_data=f"qaans:{r.id}")])
    await tg.send_text(update.effective_message, 
        "\n".join(lines)[:3900], parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(rows)
    )


async def qa_open(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    await _render(update, context, int(q.data.split(":")[1]))


async def qa_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    context.user_data["qa"] = {"lesson_id": int(q.data.split(":")[1]), "parent_id": None}
    await q.message.reply_text("✍️ أرسل سؤالك (اكتب /cancel للإلغاء):")
    return AWAIT_BODY


async def qa_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    did = int(q.data.split(":")[1])
    async with SessionLocal() as s:
        parent = await s.get(Discussion, did)
    if not parent:
        await q.message.reply_text("النقاش غير موجود.")
        return ConversationHandler.END
    context.user_data["qa"] = {"lesson_id": parent.lesson_id, "parent_id": parent.id}
    await q.message.reply_text("↩️ أرسل ردّك (اكتب /cancel للإلغاء):")
    return AWAIT_BODY


async def qa_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    data = context.user_data.pop("qa", None)
    body = (update.message.text or "").strip()
    if not data or not body:
        await tg.send_text(update.message, "لا يمكن حفظ نص فارغ.")
        return ConversationHandler.END
    tg_id = update.effective_user.id
    async with SessionLocal() as s:
        from core.repo import get_user_by_telegram

        user = await get_user_by_telegram(s, tg_id)
        if not user:
            await tg.send_text(update.message, "سجّل دخولك أولا عبر /start.")
            return ConversationHandler.END
        s.add(Discussion(
            lesson_id=data["lesson_id"], user_id=user.id,
            parent_id=data.get("parent_id"), body=body[:2000],
        ))
        await s.commit()
    await tg.send_text(update.message, "✅ نُشر مشاركتك في النقاش.")
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("qa", None)
    await tg.send_text(update.message, "تم الإلغاء.")
    return ConversationHandler.END


def qa_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(qa_ask, pattern=r"^qaask:\d+$"),
            CallbackQueryHandler(qa_answer, pattern=r"^qaans:\d+$"),
        ],
        states={AWAIT_BODY: [MessageHandler(filters.TEXT & ~filters.COMMAND, qa_save)]},
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
        per_message=True,
    )


def register_handlers(app) -> None:
    app.add_handler(CallbackQueryHandler(qa_open, pattern=r"^qa:\d+$"))
