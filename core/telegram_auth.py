# -*- coding: utf-8 -*-
"""التحقق من بيانات Telegram WebApp (initData) — وفق التوثيق الرسمي."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from core.config import settings
from core.logging import get_logger

log = get_logger("core.telegram_auth")


def verify_init_data(init_data: str, max_age_sec: int = 86400) -> dict | None:
    """يُرجع بيانات المستخدم إن كان التوقيع صحيحا، وإلا None."""
    if not init_data or not settings.BOT_TOKEN:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = pairs.pop("hash", None)
        if not received_hash:
            return None

        data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
        secret_key = hmac.new(
            b"WebAppData", settings.BOT_TOKEN.encode("utf-8"), hashlib.sha256
        ).digest()
        computed = hmac.new(
            secret_key, data_check_string.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(computed, received_hash):
            return None

        auth_date = int(pairs.get("auth_date", "0") or 0)
        if auth_date and (time.time() - auth_date) > max_age_sec:
            log.warning("initData منتهية الصلاحية.")
            return None

        user = json.loads(pairs.get("user", "{}"))
        return user or None
    except Exception as e:  # noqa: BLE001
        log.warning("فشل التحقق من initData: %s", e)
        return None
