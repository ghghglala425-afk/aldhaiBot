# -*- coding: utf-8 -*-
"""حدّ معدّل بسيط في الذاكرة (نافذة زمنية لكل مستخدم+مفتاح).

الغرض: منع إساءة استخدام الميزات المكلفة (المساعد الذكي، تشغيل الكود، البحث، الأدوات)
دون الحاجة إلى Redis.
"""
from __future__ import annotations

import time
from collections import defaultdict

from telegram import Update

# (key, user_id) -> قائمة الطوابع الزمنية
_hits: dict[tuple[str, int], list[float]] = defaultdict(list)

# الحدود: (عدد الطلبات, النافذة بالثواني)
LIMITS: dict[str, tuple[int, int]] = {
    "ask": (12, 300),
    "run": (10, 300),
    "search": (30, 300),
    "tools": (20, 300),
    "export": (20, 600),
    # التوليد مكلف (يستهلك حصة AI المجانية) — نحدّه لكل مستخدم
    "outline": (3, 3600),     # بناء مخطط لغة: 3 في الساعة
    "warm": (2, 3600),       # تسخين دروس: 2 في الساعة
    "gen": (20, 3600),       # توليد درس واحد: 20 في الساعة
}


def allow(user_id: int, key: str) -> bool:
    """هل يُسمح بطلب جديد الآن؟ (يُسجّل الطلب إن سُمح)."""
    rule = LIMITS.get(key)
    if not rule:
        return True
    count, window = rule
    now = time.monotonic()
    bucket = _hits[(key, user_id)]
    bucket[:] = [t for t in bucket if now - t < window]
    if len(bucket) >= count:
        return False
    bucket.append(now)
    return True


def retry_in(user_id: int, key: str) -> int:
    """كم ثانية حتى يُسمح بطلب جديد."""
    rule = LIMITS.get(key)
    if not rule:
        return 0
    count, window = rule
    bucket = _hits.get((key, user_id)) or []
    if len(bucket) < count:
        return 0
    return max(1, int(window - (time.monotonic() - bucket[0])))


async def guard(update: Update, key: str) -> bool:
    """يتحقق ويرسل تنبيها عند التجاوز. يُرجع True إن سُمح."""
    user = update.effective_user
    if user is None:
        return True
    if allow(user.id, key):
        return True
    wait = retry_in(user.id, key)
    msg = update.effective_message
    if msg:
        await msg.reply_text(f"⏳ طلبات كثيرة. انتظر {wait} ثانية ثم أعد المحاولة.")
    return False


def reset() -> None:
    _hits.clear()
