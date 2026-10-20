# -*- coding: utf-8 -*-
"""مساعدات مشتركة لمعالجات البوت."""
from __future__ import annotations

import asyncio

from telegram import Message, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from core.db import SessionLocal
from core.repo import get_user_by_telegram

TG_LIMIT = 3800


def esc(text: str | None) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_bg_tasks: set[asyncio.Task] = set()


def spawn(coro) -> asyncio.Task:
    """يشغّل مهمة خلفية مع حفظ مرجع (كي لا يجمعها جامع المهملات)."""
    t = asyncio.create_task(coro)
    _bg_tasks.add(t)
    t.add_done_callback(_bg_tasks.discard)
    return t


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
    """يقسّم النص عند حدود الأسطر بدل قطع الكلمات في المنتصف."""
    text = text or ""
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    buf = ""
    for line in text.splitlines(keepends=True):
        if len(buf) + len(line) > limit:
            if buf:
                parts.append(buf)
                buf = ""
            while len(line) > limit:
                parts.append(line[:limit])
                line = line[limit:]
        buf += line
    if buf:
        parts.append(buf)
    return parts


def ai_error_text(err: Exception | str | None) -> str:
    """رسالة عربية واضحة لمشاكل مزوّد الذكاء الاصطناعي (بدل صمت أو خطأ غامض)."""
    text = str(err or "")
    low = text.lower()
    if "مفتاح غير صالح" in text or "401" in text or "unauthenticated" in low or "api key not valid" in low:
        return (
            "مفتاح الذكاء الاصطناعي غير صالح أو منتهٍ.\n"
            "حدّث GEMINI_API_KEY (أو أضف GROQ_API_KEY) في إعدادات الخادم ثم أعد المحاولة."
        )
    if "نفدت" in text or "429" in text or "quota" in low or "exhausted" in low:
        return (
            "نفدت حصة الذكاء الاصطناعي المتاحة.\n"
            "ارفع AI_DAILY_TOKEN_BUDGET أو أضف مزوّدا/مفتاحا احتياطيا، ثم أعد المحاولة."
        )
    if "فشل كل المزوّدين" in text:
        return "خدمة الذكاء الاصطناعي غير متاحة الآن (تحقّق من المفاتيح والحصة في الخادم)."
    if "timeout" in low or "مهلة" in text or "timed out" in low:
        return "انتهت مهلة انتظار مزوّد الذكاء الاصطناعي. أعد المحاولة بعد لحظات."
    if "no such table" in low or "operationalerror" in low:
        return (
            "قاعدة البيانات غير مهيأة بعد.\n"
            "شغّل تهيئة القاعدة (python -m scripts.init_db) أو أعد نشر التطبيق."
        )
    return f"تعذّر الاتصال بالذكاء الاصطناعي: {text[:180]}"


async def reply_long(message: Message, text: str, *, parse_mode: str | None = None) -> None:
    for part in chunk_text(text):
        await message.reply_text(part, parse_mode=parse_mode)


async def send_long(bot, chat_id: int, text: str, *, parse_mode: str | None = None) -> None:
    for part in chunk_text(text):
        await bot.send_message(chat_id, part, parse_mode=parse_mode)


def esc_pre(text: str | None) -> str:
    return f"<pre>{esc(text)}</pre>"


async def animate_status(
    message: Message, stop: asyncio.Event, base: str, *, every: int = 8, note: str = ""
) -> None:
    """يحدّث رسالة الانتظار دوريا ليعرف المستخدم أن العمل جارٍ (لا صمت)."""
    elapsed = 0
    suffix = note or "نجهّز المحتوى…"
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=every)
            return
        except asyncio.TimeoutError:
            pass
        elapsed += every
        try:
            await message.edit_text(
                f"{base}\n\n<i>مضى {elapsed} ثانية… {suffix}</i>",
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception:  # noqa: BLE001
            pass


HTML = ParseMode.HTML
MD = ParseMode.MARKDOWN
