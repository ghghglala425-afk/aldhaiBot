# -*- coding: utf-8 -*-
"""معالجات المسارات التعلّمية."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from core import paths as svc
from core.db import SessionLocal
from core.logging import get_logger
from core.repo import get_user_by_telegram

log = get_logger("bot.paths")


async def paths_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with SessionLocal() as s:
        user = await get_user_by_telegram(s, update.effective_user.id)
        if not user:
            await update.effective_message.reply_text("سجّل دخولك أولا عبر /start.")
            return
        rows = await svc.list_paths(s)
        data = [await svc.path_progress(s, user, p) for p in rows]
    if not data:
        await update.effective_message.reply_text("لا توجد مسارات بعد.")
        return
    lines = ["🛤️ *المسارات التعلّمية:*\n"]
    for d in data:
        lines.append(f"{d['icon'] or '•'} *{d['title']}* — {d['percent']}% ({d['passed']}/{d['total']})")
    kb = [[InlineKeyboardButton(f"{d['icon'] or '•'} {d['title']}", callback_data=f"path:{d['slug']}")]
          for d in data]
    await update.effective_message.reply_text(
        "\n".join(lines), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb)
    )


async def path_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    slug = q.data.split(":", 1)[1]
    async with SessionLocal() as s:
        user = await get_user_by_telegram(s, update.effective_user.id)
        path = await svc.get_path(s, slug)
        if not path or not user:
            await q.edit_message_text("غير متاح.")
            return
        d = await svc.path_progress(s, user, path)
    text = (
        f"{d['icon'] or '•'} *{d['title']}*\n{d['description'] or ''}\n\n"
        f"التقدّم: {d['passed']}/{d['total']} ({d['percent']}%)\n"
        f"الكورسات: {'، '.join(d['courses'])}\n"
    )
    if d["certificate"]:
        text += f"\n🎓 شهادة المسار: `{d['certificate']}`"
    await q.edit_message_text(text, parse_mode="Markdown")


def register_handlers(app) -> None:
    app.add_handler(CommandHandler("paths", paths_cmd))
    app.add_handler(CallbackQueryHandler(path_callback, pattern=r"^path:[\w\-]+$"))
