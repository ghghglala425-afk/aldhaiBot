# -*- coding: utf-8 -*-
"""أدوات اختبار الويب (Burp-lite): إعادة الإرسال (Repeater)، تخمين المعاملات،
والترميز/فك الترميز. محصورة بنطاقات مسموحة لتجنّب إساءة الاستخدام.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import html
import time
import urllib.parse
from urllib.parse import urlparse

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.logging import get_logger
from core.models import ProxyLog, User

log = get_logger("core.proxy")


class ProxyError(RuntimeError):
    pass


def _host_allowed(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:  # noqa: BLE001
        return False
    allowed = settings.allowed_proxy_hosts
    if not allowed:
        allowed = ["localhost", "127.0.0.1"]
    for a in allowed:
        if host == a or host.endswith("." + a):
            return True
    return False


async def send(
    session: AsyncSession,
    user: User | None,
    *,
    method: str,
    url: str,
    headers: dict | None = None,
    body: str | None = None,
) -> dict:
    if not _host_allowed(url):
        raise ProxyError("النطاق غير مسموح. أضفه إلى PROXY_ALLOWED_HOSTS.")
    method = (method or "GET").upper()
    hdrs = {k: v for k, v in (headers or {}).items() if k}
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=settings.PROXY_TIMEOUT, follow_redirects=False) as client:
            resp = await client.request(method, url, headers=hdrs, content=(body or None))
    except httpx.HTTPError as e:
        raise ProxyError(f"فشل الطلب: {e}") from e
    dur = int((time.perf_counter() - start) * 1000)
    text = resp.text
    out = {
        "status": resp.status_code,
        "headers": dict(resp.headers),
        "body": text[:20000],
        "length": len(text),
        "duration_ms": dur,
    }
    session.add(
        ProxyLog(
            user_id=user.id if user else None, method=method, url=url, req_headers=hdrs,
            req_body=(body or None), status_code=resp.status_code,
            resp_headers=dict(resp.headers), resp_body=text[:20000], duration_ms=dur,
        )
    )
    await session.commit()
    return out


async def fuzz(
    session: AsyncSession,
    user: User | None,
    *,
    url: str,
    method: str = "GET",
    payloads: list[str],
    marker: str = "FUZZ",
    headers: dict | None = None,
    body: str | None = None,
) -> list[dict]:
    if not _host_allowed(url.replace(marker, "x") if marker in url else url):
        raise ProxyError("النطاق غير مسموح.")
    results: list[dict] = []
    for p in payloads[:200]:
        target = url.replace(marker, urllib.parse.quote(p)) if marker in url else url
        b = (body or "").replace(marker, p) if body else None
        try:
            async with httpx.AsyncClient(timeout=settings.PROXY_TIMEOUT, follow_redirects=False) as client:
                start = time.perf_counter()
                resp = await client.request(method.upper(), target, headers=headers or {}, content=b)
                dur = int((time.perf_counter() - start) * 1000)
            results.append({"payload": p, "status": resp.status_code, "length": len(resp.text),
                            "duration_ms": dur})
        except httpx.HTTPError as e:
            results.append({"payload": p, "status": 0, "error": str(e)[:120]})
    return results


def decode(op: str, value: str) -> dict:
    op = (op or "").lower()
    try:
        if op == "b64e":
            r = base64.b64encode(value.encode()).decode()
        elif op == "b64d":
            r = base64.b64decode(value + "=" * (-len(value) % 4)).decode("utf-8", "replace")
        elif op == "urle":
            r = urllib.parse.quote(value)
        elif op == "urld":
            r = urllib.parse.unquote(value)
        elif op == "hexe":
            r = binascii.hexlify(value.encode()).decode()
        elif op == "hexd":
            r = binascii.unhexlify(value).decode("utf-8", "replace")
        elif op == "htmle":
            r = html.escape(value)
        elif op == "htmld":
            r = html.unescape(value)
        elif op in {"md5", "sha1", "sha256"}:
            r = hashlib.new(op, value.encode()).hexdigest()
        else:
            return {"ok": False, "error": "عملية غير معروفة."}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
    return {"ok": True, "result": r}
