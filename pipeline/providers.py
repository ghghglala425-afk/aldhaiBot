# -*- coding: utf-8 -*-
"""طبقة المزوّدين المجانيين (Gemini / Groq / OpenRouter) مع تبديل تلقائي.

- كل مزوّد يُستدعى عبر نقطة نهاية متوافقة مع OpenAI (أو Gemini native endpoint).
- العدّاد اليومي (جدول AIUsage) يمنع تجاوز الحصص المجانية.
- عند 429/نفاد الحصة ينتقل المزوّد إلى تبريد ويُجرَّب التالي فوراً.
- المفاتيح المتعددة لنفس المزوّد تضاعف الحصة (GEMINI_API_KEY + GEMINI_API_KEY_2).
"""
from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass, field, replace
from typing import Any

import httpx
from sqlalchemy import select

from core.config import settings
from core.logging import get_logger

log = get_logger("pipeline.providers")


class ProviderError(RuntimeError):
    """فشل مزوّد واحد (يسمح بالانتقال إلى التالي)."""


class AllProvidersFailed(ProviderError):
    pass


class QuotaExhausted(ProviderError):
    """الحصة اليومية للمزوّد (أو الميزانية الإجمالية) نفدت."""


@dataclass
class ProviderSpec:
    name: str
    base_url: str
    model: str
    api_key: str
    rpm: int = 0
    rpd: int = 0
    tpd: int = 0
    native: bool = False  # Gemini native (غير OpenAI-compatible)
    json_object: bool = True
    _last_call: float = field(default=0.0, repr=False)
    _cooldown_until: float = field(default=0.0, repr=False)

    @property
    def key_id(self) -> str:
        return f"{self.name}:{self.api_key[-4:]}" if self.api_key else self.name

    def ready(self) -> bool:
        return time.monotonic() >= self._cooldown_until

    def cool(self, seconds: float) -> None:
        self._cooldown_until = time.monotonic() + max(1.0, seconds)

    async def throttle(self) -> None:
        """يبقي التردد تحت RPM المعلن."""
        if self.rpm <= 0:
            return
        gap = 60.0 / self.rpm
        wait = gap - (time.monotonic() - self._last_call)
        if wait > 0:
            import asyncio

            await asyncio.sleep(min(wait, 10))
        self._last_call = time.monotonic()


# ---------------------------------------------------------------------
#  بناء المزوّدين من الإعدادات
# ---------------------------------------------------------------------
def build_providers(settings_override=None) -> list[ProviderSpec]:
    """بناء قائمة المزوّدين.
    `settings_override`: كائن Settings اختياري للاختبار (الافتراضي = الإعدادات العامة).
    """
    s = settings_override or settings
    out: list[ProviderSpec] = []
    for name in s.free_providers:
        if name == "gemini":
            for key in (s.GEMINI_API_KEY, s.GEMINI_API_KEY_2):
                if not key:
                    continue
                out.append(
                    ProviderSpec(
                        name="gemini",
                        base_url="https://generativelanguage.googleapis.com/v1beta",
                        model=s.GEMINI_MODEL,
                        api_key=key,
                        rpm=s.GEMINI_RPM,
                        rpd=s.GEMINI_RPD,
                        tpd=s.GEMINI_TPD,
                        native=True,
                    )
                )
        elif name == "groq":
            if s.GROQ_API_KEY:
                out.append(
                    ProviderSpec(
                        name="groq",
                        base_url="https://api.groq.com/openai/v1",
                        model=s.GROQ_MODEL,
                        api_key=s.GROQ_API_KEY,
                        rpm=s.GROQ_RPM,
                        rpd=s.GROQ_RPD,
                        tpd=s.GROQ_TPD,
                    )
                )
        elif name == "openrouter":
            if s.OPENROUTER_API_KEY:
                out.append(
                    ProviderSpec(
                        name="openrouter",
                        base_url="https://openrouter.ai/api/v1",
                        model=s.OPENROUTER_MODEL,
                        api_key=s.OPENROUTER_API_KEY,
                        rpm=s.OPENROUTER_RPM,
                        rpd=s.OPENROUTER_RPD,
                        tpd=s.OPENROUTER_TPD,
                    )
                )
    return out


# ---------------------------------------------------------------------
#  العدّاد اليومي (DB)
# ---------------------------------------------------------------------
async def _usage_row(session, provider: str) -> Any:
    from core.models import AIUsage

    today = dt.date.today()
    row = await session.scalar(
        select(AIUsage).where(AIUsage.provider == provider, AIUsage.day == today)
    )
    if row is None:
        row = AIUsage(provider=provider, day=today)
        session.add(row)
        await session.flush()
    return row


async def _budget_left(session) -> int | None:
    """الميزانية الإجمالية المتبقية اليوم (None = بلا سقف)."""
    if settings.AI_DAILY_TOKEN_BUDGET <= 0:
        return None
    from core.models import AIUsage

    today = dt.date.today()
    total = await session.scalar(
        select(func_sum(AIUsage.tokens)).where(AIUsage.day == today)
    )
    return max(0, settings.AI_DAILY_TOKEN_BUDGET - int(total or 0))


def func_sum(col):
    from sqlalchemy import func

    return func.coalesce(func.sum(col), 0)


async def budget_left() -> int | None:
    """الميزانية المتبقية اليوم من خارج جلسة (None = بلا سقف)."""
    from core.db import SessionLocal

    try:
        async with SessionLocal() as session:
            return await _budget_left(session)
    except Exception as e:  # noqa: BLE001
        log.debug("تعذّر حساب الميزانية: %s", e)
        return None


async def budget_reserve() -> int:
    """الحصة المحجوزة للتفاعل الفوري (لا تستهلكها مهام الخلفية)."""
    pct = max(0, min(90, int(getattr(settings, "AI_RESERVE_PCT", 25) or 0)))
    if settings.AI_DAILY_TOKEN_BUDGET <= 0 or pct == 0:
        return 0
    return int(settings.AI_DAILY_TOKEN_BUDGET * pct / 100)


async def interactive_headroom() -> tuple[int, int]:
    """(توكنز متبقية بعد الحجز, أضيق حد متبقٍ للمزوّد الأول طلبات/توكنز).

    تُستخدم لحماية التفاعل الفوري (المساعد/فتح الدرس) من جوع مهام الخلفية.
    """
    from core.db import SessionLocal

    big = 10**9
    try:
        async with SessionLocal() as session:
            left = await _budget_left(session)
            left_after = big if left is None else left - await budget_reserve()
            specs = [p for p in build_providers() if p.ready()]
            if not specs:
                return left_after, 0
            spec = specs[0]
            row = await _usage_row(session, spec.name)
            reqs_left = (spec.rpd - row.requests) if spec.rpd else big
            tok_left = (spec.tpd - row.tokens) if spec.tpd else big
            return left_after, min(reqs_left, tok_left)
    except Exception as e:  # noqa: BLE001
        log.debug("تعذّر حساب مساحة التفاعل: %s", e)
        return big, big


async def _can_call(session, spec: ProviderSpec) -> bool:
    row = await _usage_row(session, spec.name)
    if spec.rpd and row.requests >= spec.rpd:
        return False
    if spec.tpd and row.tokens >= spec.tpd:
        return False
    left = await _budget_left(session)
    if left is not None and left <= 0:
        return False
    return True


async def _record(session, spec: ProviderSpec, tokens: int, *, error: bool = False) -> None:
    row = await _usage_row(session, spec.name)
    row.requests = (row.requests or 0) + 1
    row.tokens = (row.tokens or 0) + max(0, tokens)
    if error:
        row.errors = (row.errors or 0) + 1
    row.updated_at = dt.datetime.now(dt.timezone.utc)
    await session.commit()


# ---------------------------------------------------------------------
#  النداءات
# ---------------------------------------------------------------------
def _openai_payload(
    spec: ProviderSpec, system: str, user: str, *, temperature: float,
    max_tokens: int | None, mode: str,
) -> dict:
    payload: dict[str, Any] = {
        "model": spec.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "stream": False,
    }
    if max_tokens:
        payload["max_tokens"] = max_tokens
    if mode == "json_object" and spec.json_object:
        payload["response_format"] = {"type": "json_object"}
    return payload


def _gemini_payload(
    system: str, user: str, *, temperature: float, max_tokens: int | None, mode: str
) -> dict:
    gen: dict[str, Any] = {"temperature": temperature}
    if max_tokens:
        gen["maxOutputTokens"] = max_tokens
    if mode == "json_object":
        gen["responseMimeType"] = "application/json"
    return {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": gen,
    }


def _parse_gemini(data: dict) -> tuple[str, int]:
    try:
        cand = data["candidates"][0]
        parts = cand["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts)
    except Exception as e:  # noqa: BLE001
        raise ProviderError(f"استجابة Gemini غير متوقعة: {e}") from e
    usage = data.get("usageMetadata") or {}
    tokens = int(usage.get("totalTokenCount") or 0)
    return text, tokens


def _parse_openai(data: dict) -> tuple[str, int]:
    try:
        text = data["choices"][0]["message"]["content"]
    except Exception as e:  # noqa: BLE001
        raise ProviderError(f"استجابة غير متوقعة: {e}") from e
    usage = data.get("usage") or {}
    tokens = int(usage.get("total_tokens") or 0)
    return text or "", tokens


def _retry_after(resp: httpx.Response) -> float:
    raw = resp.headers.get("retry-after") or ""
    try:
        return float(raw)
    except ValueError:
        return 60.0


async def _call_one(
    spec: ProviderSpec, system: str, user: str, *, temperature: float,
    max_tokens: int | None, mode: str, timeout: float | None = None,
) -> tuple[str, int]:
    await spec.throttle()
    read_timeout = float(timeout or settings.AI_TIMEOUT)
    http_timeout = httpx.Timeout(read_timeout, connect=min(15.0, read_timeout))
    async with httpx.AsyncClient(timeout=http_timeout) as client:
        if spec.native:
            url = f"{spec.base_url}/models/{spec.model}:generateContent?key={spec.api_key}"
            body = _gemini_payload(
                system, user, temperature=temperature, max_tokens=max_tokens, mode=mode
            )
            resp = await client.post(url, json=body)
        else:
            url = f"{spec.base_url.rstrip('/')}/chat/completions"
            body = _openai_payload(
                spec, system, user, temperature=temperature,
                max_tokens=max_tokens, mode=mode,
            )
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {spec.api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://t.me/TrsttryBot",
                    "X-Title": "Cyber Academy",
                },
                json=body,
            )
    if resp.status_code in (401, 403):
        raise ProviderError(f"{spec.name}: مفتاح غير صالح ({resp.status_code})")
    if resp.status_code == 429:
        spec.cool(_retry_after(resp))
        raise QuotaExhausted(f"{spec.name}: تجاوز الحد (429)")
    if resp.status_code >= 400:
        raise ProviderError(f"{spec.name}: HTTP {resp.status_code} {resp.text[:180]}")
    data = resp.json()
    return _parse_gemini(data) if spec.native else _parse_openai(data)


async def _call_with_fallback(
    spec: ProviderSpec, system: str, user: str, *, temperature: float,
    max_tokens: int | None, mode: str, timeout: float | None = None,
) -> tuple[str, int]:
    """ينادي المزوّد، ويجرّب موديل Gemini بديلا إذا كان اسم الموديل غير مدعوم."""
    try:
        return await _call_one(
            spec, system, user, temperature=temperature,
            max_tokens=max_tokens, mode=mode, timeout=timeout,
        )
    except ProviderError as e:
        fallback = settings.GEMINI_FALLBACK_MODEL
        low = str(e).lower()
        unsupported = "404" in str(e) or "not found" in low or "not supported" in low
        if spec.native and fallback and fallback != spec.model and unsupported:
            log.warning("موديل %s غير متاح — تجربة %s", spec.model, fallback)
            text, tokens = await _call_one(
                replace(spec, model=fallback), system, user,
                temperature=temperature, max_tokens=max_tokens, mode=mode, timeout=timeout,
            )
            spec.model = fallback
            return text, tokens
        raise


async def complete(
    system: str,
    user: str,
    *,
    temperature: float = 0.4,
    max_tokens: int | None = None,
    mode: str = "json_object",
    timeout: float | None = None,
) -> tuple[str, str]:
    """يجرّب المزوّدين بالترتيب. يُرجع (النص, اسم المزوّد)."""
    from core.db import SessionLocal

    providers = build_providers()
    if not providers:
        raise AllProvidersFailed("لا يوجد مزوّد مجاني مضبوط")

    errors: list[str] = []
    for spec in providers:
        if not spec.ready():
            errors.append(f"{spec.name}: في تبريد")
            continue
        async with SessionLocal() as session:
            if not await _can_call(session, spec):
                errors.append(f"{spec.name}: نفدت حصته اليومية")
                continue
            try:
                text, tokens = await _call_with_fallback(
                    spec, system, user, temperature=temperature,
                    max_tokens=max_tokens, mode=mode, timeout=timeout,
                )
            except QuotaExhausted as e:
                await _record(session, spec, 0, error=True)
                errors.append(str(e))
                continue
            except Exception as e:  # noqa: BLE001
                await _record(session, spec, 0, error=True)
                errors.append(f"{spec.name}: {e}")
                continue
            await _record(session, spec, tokens)
        log.info("AI عبر %s (%s توكن)", spec.name, tokens)
        return text, spec.name

    raise AllProvidersFailed("فشل كل المزوّدين: " + " | ".join(errors[:4]))


async def usage_snapshot() -> list[dict]:
    """لقطة استهلاك اليوم (للوحة المشرف)."""
    from core.db import SessionLocal
    from core.models import AIUsage

    today = dt.date.today()
    async with SessionLocal() as session:
        rows = list(
            (
                await session.execute(
                    select(AIUsage).where(AIUsage.day == today).order_by(AIUsage.provider)
                )
            )
            .scalars()
            .all()
        )
    return [
        {
            "provider": r.provider,
            "requests": r.requests,
            "tokens": r.tokens,
            "errors": r.errors,
        }
        for r in rows
    ]
