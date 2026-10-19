# -*- coding: utf-8 -*-
"""معالجات المصادقة: تسجيل جديد ودخول عبر محادثة متعددة الخطوات."""
from __future__ import annotations

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from app.keyboards import main_reply_kb
from core.db import SessionLocal
from core.logging import get_logger
from core.repo import (
    authenticate,
    get_user_by_telegram,
    link_telegram,
    register_email,
)

log = get_logger("bot.auth")

ASK_EMAIL, ASK_PASSWORD = range(2)


async def entry_register(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["auth_mode"] = "register"
    q = update.callback_query
    if q:
        await q.answer()
        await q.edit_message_text("📧 أرسل بريدك الإلكتروني للتسجيل:")
    else:
        await update.message.reply_text("📧 أرسل بريدك الإلكتروني للتسجيل:")
    return ASK_EMAIL


async def entry_login(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["auth_mode"] = "login"
    q = update.callback_query
    if q:
        await q.answer()
        await q.edit_message_text("📧 أرسل بريدك الإلكتروني للدخول:")
    else:
        await update.message.reply_text("📧 أرسل بريدك الإلكتروني للدخول:")
    return ASK_EMAIL


async def got_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    email = (update.message.text or "").strip()
    if "@" not in email or "." not in email:
        await update.message.reply_text("صيغة البريد غير صحيحة. أعد الإرسال:")
        return ASK_EMAIL
    context.user_data["email"] = email
    mode = context.user_data.get("auth_mode", "login")
    word = "المرغوب" if mode == "register" else "الخاص بحسابك"
    await update.message.reply_text(f"🔒 أرسل كلمة المرور {word}:")
    return ASK_PASSWORD


async def got_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    password = (update.message.text or "").strip()
    email = context.user_data.get("email", "")
    mode = context.user_data.get("auth_mode", "login")
    tg_id = update.effective_user.id

    # امسح كلمة المرور من الرسالة لمنع بقائها في السجلّ
    try:
        await update.message.delete()
    except Exception:
        pass

    async with SessionLocal() as session:
        if mode == "register":
            user, err = await register_email(session, email, password)
        else:
            user, err = await authenticate(session, email, password)
        if err or not user:
            await update.message.reply_text(
                f"❌ {err or 'فشل الدخول.'}\nأرسل /start للمحاولة مجددا."
            )
            return ConversationHandler.END
        try:
            await link_telegram(session, user, tg_id)
        except PermissionError as e:
            await update.message.reply_text(f"🔒 {e}\nاستخدم حسابا آخر أو تواصل مع الدعم.")
            return ConversationHandler.END
        name = user.username or user.email

    await update.message.reply_text(
        f"✅ تم {'إنشاء الحساب' if mode == 'register' else 'الدخول'} بنجاح، أهلا {name}!\n"
        "استخدم الأزرار بالأسفل للبدء.",
        reply_markup=main_reply_kb(),
    )
    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("تم الإلغاء. أرسل /start للبدء.")
    return ConversationHandler.END


def auth_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CallbackQueryHandler(entry_register, pattern="^auth:register$"),
            CallbackQueryHandler(entry_login, pattern="^auth:login$"),
            CommandHandler("register", entry_register),
            CommandHandler("login", entry_login),
        ],
        states={
            ASK_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_email)],
            ASK_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_password)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )
