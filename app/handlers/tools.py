# -*- coding: utf-8 -*-
"""أدوات اختبار الويب داخل البوت (Burp-lite): Repeater + Decoder + Fuzzer-lite."""
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
from core.db import SessionLocal
from core.logging import get_logger
from core.proxy import ProxyError, decode, send
from core.repo import get_user_by_telegram
from app import tg

log = get_logger("bot.tools")

AWAIT_ACTION, AWAIT_VALUE, AWAIT_REQ = range(800, 803)

OPS = [
    ("b64e", "Base64 تشفير"), ("b64d", "Base64 فك"),
    ("urle", "URL تشفير"), ("urld", "URL فك"),
    ("hexe", "Hex تشفير"), ("hexd", "Hex فك"),
    ("htmle", "HTML تشفير"), ("htmld", "HTML فك"),
    ("md5", "MD5"), ("sha1", "SHA1"), ("sha256", "SHA256"),
]

MENU_TEXT = (
    "🕵️ *أدوات اختبار الويب*\n\n"
    "• 🔁 *Repeater*: أرسل طلب HTTP واعرض الاستجابة.\n"
    "• 🔐 *Decoder*: ترميز/فك ترميز وتجزئة (11 عملية).\n\n"
    f"النطاقات المسموحة: `{settings.PROXY_ALLOWED_HOSTS or 'localhost,127.0.0.1'}`"
)


def _menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔁 Repeater", callback_data="t:repeater")],
        [InlineKeyboardButton("🔐 Decoder", callback_data="t:decoder")],
    ])


def _ops_kb() -> InlineKeyboardMarkup:
    rows, row = [], []
    for op, label in OPS:
        row.append(InlineKeyboardButton(label, callback_data=f"dec:{op}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)


async def tools_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    from app import ratelimit

    if not await ratelimit.guard(update, "tools"):
        return ConversationHandler.END
    await tg.send_text(update.message, MENU_TEXT, parse_mode=ParseMode.MARKDOWN, reply_markup=_menu_kb())
    return AWAIT_ACTION


async def got_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    action = q.data.split(":", 1)[1]
    if action == "decoder":
        context.user_data["t_mode"] = "decode"
        await tg.edit_text(q, "🔐 اختر العملية:", reply_markup=_ops_kb())
        return AWAIT_ACTION
    context.user_data["t_mode"] = "repeater"
    await tg.edit_text(q, 
        "🔁 أرسل الطلب بصيغة:\n`GET https://example.com/`\nأو مع جسم:\n`POST https://example.com | a=1&b=2`"
    )
    return AWAIT_REQ


async def got_op(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    op = q.data.split(":", 1)[1]
    context.user_data["t_op"] = op
    await tg.edit_text(q, "✍️ أرسل القيمة المطلوب معالجتها (اكتب /cancel للإلغاء):")
    return AWAIT_VALUE


async def got_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    op = context.user_data.pop("t_op", "")
    value = update.message.text or ""
    res = decode(op, value)
    if res.get("ok"):
        await tg.send_text(update.message, 
            f"✅ النتيجة:\n<pre>{esc(str(res['result'])[:3500])}</pre>", parse_mode=ParseMode.HTML
        )
    else:
        await tg.send_text(update.message, f"⚠️ {res.get('error')}")
    return ConversationHandler.END


async def got_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = (update.message.text or "").strip()
    method, url, body = "GET", "", None
    if "|" in raw:
        head, body = raw.split("|", 1)
        body = body.strip()
    else:
        head = raw
    parts = head.strip().split()
    if len(parts) >= 2:
        method, url = parts[0].upper(), parts[1]
    elif parts:
        url = parts[0]
    if not url:
        await tg.send_text(update.message, "صيغة غير صحيحة. مثال: GET https://example.com/")
        return ConversationHandler.END
    msg = await update.message.reply_text("⏳ أُرسل الطلب…")
    async with SessionLocal() as s:
        user = await get_user_by_telegram(s, update.effective_user.id)
        try:
            res = await send(s, user, method=method, url=url, body=body)
        except ProxyError as e:
            await msg.edit_text(f"⚠️ {e}")
            return ConversationHandler.END
    header_lines = "\n".join(f"{k}: {v}" for k, v in list(res["headers"].items())[:12])
    out = (
        f"🔁 *{method}* `{url}`\n"
        f"الحالة: `{res['status']}` · الطول: {res['length']} · {res['duration_ms']}ms\n"
    )
    if header_lines:
        out += f"\n<pre>{esc(header_lines)}</pre>"
    if res["body"]:
        out += f"\n<b>الاستجابة:</b>\n<pre>{esc(res['body'][:2200])}</pre>"
    try:
        await msg.edit_text(out[:3900], parse_mode=ParseMode.HTML)
    except Exception:  # noqa: BLE001
        await tg.send_text(update.message, out[:3900], parse_mode=ParseMode.HTML)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("t_mode", None)
    context.user_data.pop("t_op", None)
    await tg.send_text(update.message, "تم الإلغاء.")
    return ConversationHandler.END


def tools_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CommandHandler("tools", tools_cmd),
            MessageHandler(filters.Regex("^🕵️ الأدوات$"), tools_cmd),
        ],
        states={
            AWAIT_ACTION: [
                CallbackQueryHandler(got_action, pattern=r"^t:(repeater|decoder)$"),
                CallbackQueryHandler(got_op, pattern=r"^dec:[\w]+$"),
            ],
            AWAIT_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_value)],
            AWAIT_REQ: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_request)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )


def register_handlers(app) -> None:
    pass
