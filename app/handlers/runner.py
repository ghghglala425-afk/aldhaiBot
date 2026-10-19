# -*- coding: utf-8 -*-
"""تنفيذ الأكواد داخل البوت (▶️ /run) عبر الـSandbox المعزول."""
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

from app.handlers.common import esc
from core.config import settings
from core.logging import get_logger
from pipeline.sandbox_runner import _RUN, docker_available, run_code

log = get_logger("bot.runner")

AWAIT_LANG, AWAIT_CODE = range(700, 702)

LANG_LABELS = {
    "python": "🐍 بايثون",
    "javascript": "🟨 جافاسكربت",
    "bash": "🖥️ باش",
    "php": "🐘 PHP",
    "ruby": "💎 روبي",
    "c": "⚙️ سي",
    "cpp": "🧩 سي++",
}


async def _lang_keyboard() -> InlineKeyboardMarkup:
    langs = [l for l in LANG_LABELS if l in _RUN]
    rows = [[InlineKeyboardButton(LANG_LABELS[l], callback_data=f"runlang:{l}")] for l in langs]
    return InlineKeyboardMarkup(rows)


async def run_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from app import ratelimit

    if not await ratelimit.guard(update, "run"):
        return ConversationHandler.END
    docker_on = await docker_available()
    if not docker_on and not settings.SANDBOX_LOCAL:
        await update.message.reply_text(
            "▶️ تنفيذ الأكواد غير متاح حاليا.\n"
            "• شغّل Docker لتفعيل العزل، أو\n"
            "• فعّل SANDBOX_LOCAL=1 (تنفيذ محلي بلا عزل — غير موصى به)."
        )
        return ConversationHandler.END
    await update.message.reply_text("▶️ اختر لغة التنفيذ:", reply_markup=await _lang_keyboard())
    return AWAIT_LANG


async def got_lang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    lang = q.data.split(":", 1)[1]
    context.user_data["run_lang"] = lang
    await q.edit_message_text(
        f"▶️ اللغة: {LANG_LABELS.get(lang, lang)}\nأرسل الكود الآن (اكتب /cancel للإلغاء):"
    )
    return AWAIT_CODE


async def got_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = context.user_data.pop("run_lang", None)
    code = update.message.text or ""
    if not lang or not code.strip():
        await update.message.reply_text("لم يصل كود صالح.")
        return ConversationHandler.END
    msg = await update.message.reply_text("⏳ أُشغّل الكود…")
    res = await run_code(lang, code, exec_enabled=True)
    body = (
        f"▶️ *نتيجة التنفيذ* — {LANG_LABELS.get(lang, lang)}\n"
        f"الحالة: `{res.status}` · المحرّك: `{res.engine or '—'}`\n"
    )
    if res.detail:
        body += f"ملاحظة: {res.detail}\n"
    if res.stdout:
        body += f"\n<b>الخرج:</b>\n<pre>{esc(res.stdout[:2500])}</pre>"
    if res.stderr:
        body += f"\n<b>الأخطاء:</b>\n<pre>{esc(res.stderr[:1500])}</pre>"
    try:
        await msg.edit_text(body[:3900], parse_mode=ParseMode.HTML)
    except Exception:  # noqa: BLE001
        await update.message.reply_text(body[:3900], parse_mode=ParseMode.HTML)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("run_lang", None)
    await update.message.reply_text("تم الإلغاء.")
    return ConversationHandler.END


def run_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CommandHandler("run", run_cmd),
            MessageHandler(filters.Regex("^▶️ تشغيل كود$"), run_cmd),
        ],
        states={
            AWAIT_LANG: [CallbackQueryHandler(got_lang, pattern=r"^runlang:[\w\-]+$")],
            AWAIT_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_code)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )


def register_handlers(app) -> None:
    pass
