# -*- coding: utf-8 -*-
"""مولّد موسوعة الأكواد (Code Atlas).

لكل مثال كود يبني: تشريح سطر-بسطر، وكل استخداماته (≥8) مع مثال ومخرج لكل استخدام،
والمعاملات، والقيمة المُرجعة، والأخطاء الشائعة، والملاحظات الأمنية، والم topics المرتبطة.
يعمل على دفعات لتقليل عدد النداءات وزيادة الموثوقية.
"""
from __future__ import annotations

import json

from core.config import settings
from core.logging import get_logger
from pipeline.ai import AIError, chat_json
from pipeline.schema import GeneratedCode

log = get_logger("pipeline.atlas")

SYSTEM = """أنت مرجع برمجي عربي دقيق. ستحصل على قائمة أمثلة أكواد، ولكل مثال:
- تشريح سطر-بسطر (anatomy): لكل سطر مهم: رقم السطر، نصه، وشرح موجز.
- جميع الاستخدامات (usages): %d استخداما على الأقل للدالة/الأسلوب/المفهوم الأساسي،
  ولكل استخدام: الاسم، التوقيع/الصيغة (signature)، وصف، مثال كود قصير قابل للتشغيل،
  والمخرج المتوقع (output).
- parameters: المعاملات (الاسم، النوع، الوصف، الافتراضي، هل إلزامي).
- returns: وصف القيمة المُرجعة.
- gotchas: أخطاء شائعة ومزالق (نقاط قصيرة).
- security_notes: ملاحظات أمنية دقيقة (مثلا: تجنّب eval، استخدم مقارنة ثابتة الزمن...).
- related: دوال/مفاهيم مرتبطة.
- tags: وسوم قصيرة.

أرجع كائن JSON واحدا فقط بالبنية:
{"items":[
  {"index":1,
   "anatomy":[{"line":1,"code":"...","explain":"..."}],
   "usages":[{"name":"...","signature":"...","description":"...","example":"...","output":"..."}],
   "parameters":[{"name":"...","type":"...","description":"...","default":"","required":false}],
   "returns":"...",
   "gotchas":["..."],
   "security_notes":["..."],
   "related":["..."],
   "tags":["..."]}
]}
قواعد:
- لا تغيّر الأكواد الأصلية، ولا تخترع دوال غير موجودة فعليا في اللغة.
- اكتب الشرح بالعربية الفصحى المبسطة، والأكواد بالإنجليزية.
- عدَد الاستخدامات %d على الأقل لكل مثال."""


def _chunks(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


async def _enrich_batch(codes: list[GeneratedCode], language: str) -> dict[int, dict]:
    payload = {
        "items": [
            {
                "index": i,
                "title": c.title,
                "code": c.code,
                "explanation": c.explanation,
                "expected_output": c.expected_output,
            }
            for i, c in enumerate(codes, start=1)
        ]
    }
    system = SYSTEM % (settings.GEN_MIN_USAGES, settings.GEN_MIN_USAGES)
    user = (
        f"لغة البرمجة: {language}\n"
        f"العدد المطلوب للاستخدامات لكل مثال: {settings.GEN_MIN_USAGES}\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    data = await chat_json(system, user, temperature=0.2)
    out: dict[int, dict] = {}
    for item in data.get("items", []):
        try:
            out[int(item["index"])] = item
        except Exception:  # noqa: BLE001
            continue
    return out


async def enrich_codes(
    codes: list[GeneratedCode],
    language: str,
    *,
    batch_size: int | None = None,
) -> list[GeneratedCode]:
    """يُثري قائمة الأكواد بموسوعة كاملة (Best-effort: يفشل بأمان)."""
    if not codes:
        return codes
    size = batch_size or settings.GEN_ATLAS_BATCH
    merged = list(codes)

    for group in _chunks(list(range(len(codes))), size):
        part = [codes[i] for i in group]
        try:
            atlas = await _enrich_batch(part, language)
        except AIError as e:
            log.warning("فشل إثراء دفعة (%s أكواد): %s", len(part), e)
            continue

        for offset, i in enumerate(group, start=1):
            data = atlas.get(offset)
            if not data:
                continue
            base = merged[i]
            try:
                merged[i] = GeneratedCode.model_validate(
                    {
                        **base.model_dump(),
                        "anatomy": data.get("anatomy", base.anatomy),
                        "usages": data.get("usages", base.usages),
                        "parameters": data.get("parameters", base.parameters),
                        "returns": data.get("returns", base.returns),
                        "gotchas": data.get("gotchas", base.gotchas),
                        "security_notes": data.get("security_notes", base.security_notes),
                        "related": data.get("related", base.related),
                        "tags": data.get("tags", base.tags),
                    }
                )
            except Exception as e:  # noqa: BLE001
                log.warning("تخطّي إثراء كود %s: %s", i + 1, e)

    return merged
