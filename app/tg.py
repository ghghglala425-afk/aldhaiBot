# -*- coding: utf-8 -*-
"""إرسال آمن لرسائل تيليجرام.

المشكلة: المحتوى المولَّد (عناوين الدروس، أسماء اللغات…) قد يحتوي رموز
Markdown مثل `_` أو `*` فيكسر تحليل تيليجرام فيرمي
`BadRequest: can't parse entities` ويظهر للمستخدم «حدث خطأ غير متوقع».

الحل: عند فشل التحليل نعيد الإرسال كنص عادي بدل أن نفقد الرسالة.
"""
from __future__ import annotations

import logging
from typing import Any

from telegram.constants import ParseMode
from telegram.error import BadRequest

log = logging.getLogger("bot.safe")

# الرموز التي يجب تهريبها في وضع Markdown القديم (legacy)
_MD_SPECIALS = ("_", "*", "`", "[")


def escape_md(text: str | None) -> str:
    """يهرب الرموز الخاصة بـ Markdown القديم (تيليجرام v1)."""
    if not text:
        return ""
    out = str(text)
    for ch in _MD_SPECIALS:
        out = out.replace(ch, f"\\{ch}")
    return out


def _is_parse_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return (
        "can't parse entities" in msg
        or "cant parse entities" in msg
        or "unsupported start tag" in msg
    )


async def _send(func, text: str, *, parse_mode: Any = None, **kwargs) -> bool:
    """يرسل مع إعادة محاولة كنص عادي عند فشل التحليل."""
    try:
        await func(text, parse_mode=parse_mode, **kwargs)
        return True
    except BadRequest as e:
        if not _is_parse_error(e):
            raise
        log.warning("فشل تحليل التنسيق — أُرسل النص عادي: %s", str(e)[:120])
    except Exception:
        raise
    # المحاولة الثانية: نص عادي بلا تنسيق
    try:
        await func(text, parse_mode=None, **kwargs)
        return True
    except Exception as e:  # noqa: BLE001
        log.error("فشل الإرسال حتى كنص عادي: %s", e)
        return False


async def send_text(message, text: str, *, parse_mode: Any = None, **kwargs) -> bool:
    """reply_text آمن."""
    if message is None:
        return False
    return await _send(message.reply_text, text, parse_mode=parse_mode, **kwargs)


async def edit_text(query, text: str, *, parse_mode: Any = None, **kwargs) -> bool:
    """edit_message_text آمن."""
    if query is None:
        return False
    return await _send(query.edit_message_text, text, parse_mode=parse_mode, **kwargs)


async def answer(query, text: str = "", *, show_alert: bool = False, **kwargs) -> bool:
    """answer_callback_query آمن (لا يفشل بسبب النص)."""
    if query is None:
        return False
    try:
        await query.answer(text, show_alert=show_alert, **kwargs)
        return True
    except Exception as e:  # noqa: BLE001
        log.debug("تعذّر الإجابة على الاستعلام: %s", e)
        return False


__all__ = ["send_text", "edit_text", "answer", "escape_md", "ParseMode"]
