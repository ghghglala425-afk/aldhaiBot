# -*- coding: utf-8 -*-
"""تنفيذ الأكواد داخل البوت (▶️ /run) عبر الـSandbox المعزول."""
from __future__ import annotations

import time

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
from core.logging import get_logger
from pipeline.sandbox_runner import available_languages, run_code
from app import tg

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


async def _lang_keyboard(langs: list[str]) -> InlineKeyboardMarkup:
    order = [lang for lang in LANG_LABELS if lang in langs]
    rows = [[InlineKeyboardButton(LANG_LABELS[lang], callback_data=f"runlang:{lang}")] for lang in order]
    rows.append([InlineKeyboardButton("✖️ إلغاء", callback_data="runlang:cancel")])
    return InlineKeyboardMarkup(rows)


def _disabled_hint() -> str:
    return (
        "▶️ تنفيذ الأكواد غير متاح حاليا.\n\n"
        "🔒 الأمان: هذا البوت لا ينفّذ أي كود على مضيف الخادم إطلاقا.\n"
        "شغّل Docker على الخادم لتفعيل بيئة التنفيذ المعزولة ثم أعد المحاولة."
    )


async def run_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from app import ratelimit

    if not await ratelimit.guard(update, "run"):
        return ConversationHandler.END
    langs = await available_languages()
    if not langs:
        await tg.send_text(update.effective_message, _disabled_hint())
        return ConversationHandler.END
    context.user_data["run_langs"] = langs
    await tg.send_text(
        update.effective_message,
        "▶️ اختر لغة التنفيذ:\n<i>الكود يعمل في بيئة معزولة بلا وصول لأسرار الخادم.</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=await _lang_keyboard(langs),
    )
    return AWAIT_LANG


async def got_lang(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    lang = q.data.split(":", 1)[1]
    if lang == "cancel":
        context.user_data.pop("run_langs", None)
        await tg.edit_text(q, "تم الإلغاء.")
        return ConversationHandler.END
    if lang not in context.user_data.get("run_langs", []):
        await tg.edit_text(q, "هذه اللغة غير متاحة حاليا. اختر لغة أخرى عبر /run.")
        return ConversationHandler.END
    context.user_data["run_lang"] = lang
    await tg.edit_text(
        q,
        f"▶️ اللغة: {LANG_LABELS.get(lang, lang)}\n"
        "أرسل الكود الآن (اكتب /cancel للإلغاء):",
    )
    return AWAIT_CODE


async def got_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lang = context.user_data.pop("run_lang", None)
    code = update.message.text or ""
    if not lang or not code.strip():
        await tg.send_text(update.effective_message, "لم يصل كود صالح.")
        return ConversationHandler.END
    msg = await update.effective_message.reply_text("⏳ أُشغّل الكود…")
    started = time.monotonic()
    try:
        res = await run_code(lang, code, exec_enabled=True)
    except Exception as e:  # noqa: BLE001
        log.exception("فشل تشغيل الكود")
        res = None
        err_text = str(e)[:200]
    elapsed = time.monotonic() - started

    if res is None:
        body = (
            "❌ <b>تعذّر تشغيل الكود</b>\n"
            f"<i>{esc(err_text)}</i>\n\n"
            "تحقّق من صحة الكود أو أعد المحاولة."
        )
    else:
        icon = {"ok": "✅", "error": "❌", "timeout": "⏰", "skipped": "⚠️"}.get(res.status, "•")
        body = (
            f"{icon} <b>نتيجة التنفيذ</b> — {LANG_LABELS.get(lang, lang)}\n"
            f"الحالة: <code>{esc(res.status)}</code> · المحرّك: <code>{esc(res.engine or '—')}</code>"
            f" · الزمن: {elapsed:.1f}s\n"
        )
        if res.detail:
            body += f"ملاحظة: {esc(res.detail)}\n"
        if res.stdout:
            body += f"\n<b>الخرج:</b>\n<pre>{esc(res.stdout[:2500])}</pre>"
        if res.stderr:
            body += f"\n<b>الأخطاء:</b>\n<pre>{esc(res.stderr[:1500])}</pre>"
        if res.status == "skipped":
            body += "\n" + esc(_disabled_hint())
        elif res.status == "ok":
            body += "\n<i>جرّب تعديل الكود وإعادة تشغيله لتتعلم أكثر.</i>"
    try:
        await msg.edit_text(body[:3900], parse_mode=ParseMode.HTML)
    except Exception:  # noqa: BLE001
        await tg.send_text(update.effective_message, body[:3900], parse_mode=ParseMode.HTML)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("run_lang", None)
    context.user_data.pop("run_langs", None)
    await tg.send_text(update.effective_message, "تم الإلغاء.")
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
