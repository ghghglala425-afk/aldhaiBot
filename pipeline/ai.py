# -*- coding: utf-8 -*-
"""عميل الذكاء الاصطناعي (متوافق مع OpenAI: cloud / LM Studio / Ollama).

مزايا التوافق مع الموديلات المحلية:
- إرسال max_tokens (الموديلات المحلية تقصّ المخرجات الطويلة افتراضيا).
- أوضاع JSON قابلة للضبط (AI_JSON_MODE) مع تراجع تدريجي:
  json_object → json_schema → بلا قيد (استخراج JSON متسامح).
- استخراج JSON متسامح (إزالة أسوار الكود، اقتطاع من أول قوس لآخر قوس).
- إعادة محاولة مع تراجع أسّي.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import httpx

from core.config import settings
from core.logging import get_logger

log = get_logger("pipeline.ai")

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


class AIError(RuntimeError):
    pass


class AIHTTPError(AIError):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"HTTP {status}: {body[:300]}")
        self.status = status
        self.body = body


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.AI_API_KEY or 'local'}",
        "Content-Type": "application/json",
    }


def _endpoint() -> str:
    return settings.AI_BASE_URL.rstrip("/") + "/chat/completions"


def extract_json(text: str) -> Any:
    """يستخرج أول كائن/مصفوفة JSON من نص قد يحوي أسوار كود أو شرحا حوله."""
    if text is None:
        raise ValueError("مخرَج فارغ")
    raw = text.strip()
    if not raw:
        raise ValueError("مخرَج فارغ")

    candidates: list[str] = [raw]
    for m in _FENCE_RE.findall(raw):
        candidates.append(m.strip())

    obj_start = raw.find("{")
    obj_end = raw.rfind("}")
    if obj_start != -1 and obj_end > obj_start:
        candidates.append(raw[obj_start : obj_end + 1])
    arr_start = raw.find("[")
    arr_end = raw.rfind("]")
    if arr_start != -1 and arr_end > arr_start:
        candidates.append(raw[arr_start : arr_end + 1])

    last_err: Exception | None = None
    for c in candidates:
        try:
            return json.loads(c)
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise ValueError(f"تعذّر تحليل JSON: {last_err}")


def _response_format(mode: str) -> dict | None:
    if mode == "json_object":
        return {"type": "json_object"}
    if mode == "json_schema":
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "response",
                "strict": False,
                "schema": {"type": "object", "additionalProperties": True},
            },
        }
    return None


def _payload(
    system: str,
    user: str,
    *,
    temperature: float,
    model: str,
    max_tokens: int | None,
    mode: str,
) -> dict:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "stream": False,
    }
    if max_tokens:
        payload["max_tokens"] = max_tokens
    fmt = _response_format(mode)
    if fmt:
        payload["response_format"] = fmt
    return payload


async def _post(payload: dict, *, timeout: float | None = None) -> str:
    limit = float(timeout or settings.AI_TIMEOUT)
    async with httpx.AsyncClient(timeout=limit) as client:
        resp = await client.post(_endpoint(), headers=_headers(), json=payload)
    if resp.status_code >= 400:
        raise AIHTTPError(resp.status_code, resp.text)
    try:
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:  # noqa: BLE001
        raise AIError(f"استجابة غير متوقعة من الموديل: {e}") from e


async def _generate(
    system: str,
    user: str,
    *,
    temperature: float,
    model: str,
    max_tokens: int | None,
    mode: str,
    timeout: float | None = None,
) -> str:
    """ينفّذ نداء واحدا: طبقة المزوّدين المجانيين أو نقطة نهاية مباشرة."""
    if settings.ai_mode == "free":
        from pipeline.providers import complete

        text, _ = await complete(
            system,
            user,
            temperature=temperature,
            max_tokens=max_tokens,
            mode="none" if mode == "none" else "json_object",
            timeout=timeout,
        )
        return text
    payload = _payload(
        system, user, temperature=temperature, model=model,
        max_tokens=max_tokens, mode=mode,
    )
    return await _post(payload, timeout=timeout)


async def chat_json(
    system: str,
    user: str,
    *,
    temperature: float = 0.4,
    max_retries: int | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """يطلب مخرَجا JSON ويُرجع قاموسا — مع تراجع الأوضاع وإعادة المحاولة."""
    if not settings.ai_configured:
        raise AIError("لا يوجد مزوّد AI مضبوط — لا يمكن توليد المحتوى.")

    retries = max_retries or settings.AI_MAX_RETRIES
    # في الوضع المجاني كل الأوضاع تُترجم إلى json_object، لذا تكرارها يضاعف
    # زمن الفشل بلا فائدة. نجرّب وضعا واحدا ونعتمد على إعادة المحاولة.
    modes = ["json_object"] if settings.ai_mode == "free" else settings.ai_json_modes
    model = model or settings.AI_MODEL
    max_tokens = max_tokens if max_tokens is not None else settings.AI_MAX_TOKENS

    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        for mi, mode in enumerate(modes):
            try:
                content = await _generate(
                    system, user, temperature=temperature, model=model,
                    max_tokens=max_tokens, mode=mode, timeout=timeout,
                )
                data = extract_json(content)
                if not isinstance(data, dict):
                    data = {"value": data}
                return data
            except AIHTTPError as e:
                last_err = e
                # قيد JSON غير مدعوم؟ جرّب الوضع التالي مباشرة
                if e.status in (400, 404, 415, 422) and mi < len(modes) - 1:
                    log.info("وضع JSON «%s» غير مدعوم — تجربة الوضع التالي.", mode)
                    continue
                break
            except ValueError as e:
                last_err = e
                if mi < len(modes) - 1:
                    log.info("تعذّر تحليل JSON في وضع «%s» — تجربة الوضع التالي.", mode)
                    continue
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
                break
        log.warning("فشلت محاولة التوليد %s/%s: %s", attempt, retries, last_err)
        if attempt < retries:
            await asyncio.sleep(min(1.5 * attempt, 8))

    raise AIError(f"فشل التوليد بعد {retries} محاولات: {last_err}")


async def chat_text(
    system: str,
    user: str,
    *,
    temperature: float = 0.5,
    model: str | None = None,
    max_tokens: int | None = None,
    max_retries: int = 2,
    timeout: float | None = None,
) -> str:
    """نص حر (المساعد الذكي/الشروح)."""
    if not settings.ai_configured:
        raise AIError("لا يوجد مزوّد AI مضبوط.")

    model = model or settings.AI_MODEL
    max_tokens = max_tokens if max_tokens is not None else settings.AI_MAX_TOKENS

    last_err: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            return (
                await _generate(
                    system, user, temperature=temperature, model=model,
                    max_tokens=max_tokens, mode="none", timeout=timeout,
                )
            ).strip()
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt < max_retries:
                await asyncio.sleep(1.5 * attempt)
    raise AIError(f"فشل توليد النص: {last_err}")
