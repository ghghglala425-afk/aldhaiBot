# -*- coding: utf-8 -*-
"""معالجات المختبرات (CTF): عرض المختبر، التلميحات، إرسال العلم."""
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
from core.learning import labs_for_lesson, reveal_hint, submit_flag
from core.logging import get_logger
from core.models import Hint, Lab
from core.repo import get_user_by_telegram

log = get_logger("bot.labs")

AWAIT_FLAG = 100


async def lab_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    lesson_id = int(q.data.split(":")[1])
    async with SessionLocal() as s:
        labs = await labs_for_lesson(s, lesson_id)
    if not labs:
        await q.edit_message_text("لا توجد مختبرات لهذا الدرس.")
        return
    rows = [
        [
            InlineKeyboardButton(
                f"{'🎯' if l.kind == 'target' else '🧪'} {l.title}",
                callback_data=f"{'target' if l.kind == 'target' else 'lab'}:{l.id}",
            )
        ]
        for l in labs
    ]
    await q.edit_message_text("🧪 المختبرات وبيئات الهدف المتاحة:", reply_markup=InlineKeyboardMarkup(rows))


async def lab_open(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    lab_id = int(q.data.split(":")[1])
    async with SessionLocal() as s:
        lab = await s.get(Lab, lab_id)
        if not lab:
            await q.edit_message_text("المختبر غير موجود.")
            return
        hints = list(
            (await s.execute(select(Hint).where(Hint.lab_id == lab_id).order_by(Hint.order_index))).scalars().all()
        )
    text = (
        f"🧪 *{lab.title}*\n\n{lab.description or ''}\n\n"
        f"🏆 النقاط: {lab.points}\n"
        f"🎯 ابحث عن العلم بالصيغة `KHEET{...}` وأرسله."
    )
    rows = [[InlineKeyboardButton("🚩 إرسال العلم", callback_data=f"flag:{lab.id}")]]
    for i, h in enumerate(hints):
        rows.append([InlineKeyboardButton(f"💡 تلميح {i + 1} ({h.cost_xp} نقطة)", callback_data=f"hint:{lab.id}:{i}")])
    await q.edit_message_text(text[:3900], parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(rows))


async def hint_reveal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    _, lab_id, idx = q.data.split(":")
    async with SessionLocal() as s:
        lab = await s.get(Lab, int(lab_id))
        user = await get_user_by_telegram(s, update.effective_user.id)
        res = await reveal_hint(s, user, lab, int(idx))
    if res.get("ok"):
        await q.message.reply_text(f"💡 {res['hint']}\n(خُصم {res['cost']} نقطة)")
    else:
        await q.message.reply_text(f"⚠️ {res.get('error')}")


async def flag_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    lab_id = int(q.data.split(":")[1])
    context.user_data["flag_lab"] = lab_id
    await q.message.reply_text("🚩 أرسل العلم الآن (اكتب /cancel للإلغاء):")
    return AWAIT_FLAG


async def flag_submit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lab_id = context.user_data.pop("flag_lab", None)
    value = (update.message.text or "").strip()
    finally_hint = update.effective_message
    if not lab_id:
        await finally_hint.reply_text("جلسة منتهية. أعد فتح المختبر.")
        return ConversationHandler.END
    async with SessionLocal() as s:
        lab = await s.get(Lab, lab_id)
        user = await get_user_by_telegram(s, update.effective_user.id)
        if not user:
            await finally_hint.reply_text("سجّل دخولك أولا عبر /start.")
            return ConversationHandler.END
        res = await submit_flag(s, user, lab, value)
    if not res.get("ok"):
        await finally_hint.reply_text(f"⚠️ {res.get('error')}")
    elif res.get("correct"):
        await finally_hint.reply_text(f"✅ علم صحيح! +{lab.points} نقطة. أحسنت 🎉")
    else:
        await finally_hint.reply_text("❌ علم غير صحيح. حاول مرة أخرى.")
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("flag_lab", None)
    await update.message.reply_text("تم الإلغاء.")
    return ConversationHandler.END


def labs_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(flag_entry, pattern=r"^flag:\d+$")],
        states={AWAIT_FLAG: [MessageHandler(filters.TEXT & ~filters.COMMAND, flag_submit)]},
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
        per_message=True,
    )


def register_handlers(app) -> None:
    app.add_handler(CallbackQueryHandler(lab_list, pattern=r"^lab_list:\d+$"))
    app.add_handler(CallbackQueryHandler(lab_open, pattern=r"^lab:\d+$"))
    app.add_handler(CallbackQueryHandler(hint_reveal, pattern=r"^hint:\d+:\d+$"))
