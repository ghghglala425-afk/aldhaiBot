# -*- coding: utf-8 -*-
"""مساعدات مشتركة لمعالجات البوت."""
from __future__ import annotations

from telegram import Message, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from core.db import SessionLocal
from core.repo import get_user_by_telegram

TG_LIMIT = 3800


def esc(text: str | None) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def current_user(update: Update):
    """يُرجع المستخدم المرتبط بحساب تلجرام أو None."""
    tg_id = update.effective_user.id if update.effective_user else None
    if not tg_id:
        return None
    async with SessionLocal() as session:
        return await get_user_by_telegram(session, tg_id)


async def require_user(update: Update, context: ContextTypes.DEFAULT_TYPE, *, silent: bool = False):
    user = await current_user(update)
    if user is None and not silent:
        msg = update.effective_message
        if msg:
            await msg.reply_text("🔐 سجّل دخولك أولا عبر /start.")
    return user


def chunk_text(text: str, limit: int = 3500) -> list[str]:
    text = text or ""
    if len(text) <= limit:
        return [text]
    return [text[i : i + limit] for i in range(0, len(text), limit)]


async def reply_long(message: Message, text: str, *, parse_mode: str | None = None) -> None:
    for part in chunk_text(text):
        await message.reply_text(part, parse_mode=parse_mode)


async def send_long(bot, chat_id: int, text: str, *, parse_mode: str | None = None) -> None:
    for part in chunk_text(text):
        await bot.send_message(chat_id, part, parse_mode=parse_mode)


def esc_pre(text: str | None) -> str:
    return f"<pre>{esc(text)}</pre>"


HTML = ParseMode.HTML
MD = ParseMode.MARKDOWN
