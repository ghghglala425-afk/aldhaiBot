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
from pipeline.ai import chat_json
from pipeline.schema import AnatomyLine, CodeUsage, GeneratedCode, ParamInfo

log = get_logger("pipeline.atlas")

_LIST_FIELDS: tuple[tuple[str, type], ...] = (
    ("anatomy", AnatomyLine),
    ("usages", CodeUsage),
    ("parameters", ParamInfo),
)
_TEXT_FIELDS = ("returns",)
_TEXT_LIST_FIELDS = ("gotchas", "security_notes", "related", "tags")

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
    items = data.get("items") if isinstance(data, dict) else data
    if isinstance(items, dict):
        items = [items]
    if not isinstance(items, list):
        return out
    for pos, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index", item.get("id", pos)))
        except (TypeError, ValueError):
            index = pos
        out[index] = item
    # بعض النماذج ترقّم من الصفر: طبّع إلى ترقيم يبدأ من 1.
    if out and 0 in out and len(out) == len(codes) and max(out) == len(codes) - 1:
        out = {k + 1: v for k, v in out.items()}
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
        except Exception as e:  # noqa: BLE001
            log.warning("فشل إثراء دفعة (%s أكواد): %s", len(part), e)
            continue

        for offset, i in enumerate(group, start=1):
            data = atlas.get(offset)
            if not data:
                continue
            base = merged[i]
            try:
                merged[i] = _merge_atlas(base, data)
            except Exception as e:  # noqa: BLE001
                log.warning("تخطّي إثراء كود %s: %s", i + 1, e)

    return merged


def _clean_items(raw: object, model: type) -> list:
    """يحوّل عناصر قسم إلى نماذج صالحة، ويتجاهل العنصر المعطوب وحده.

    الهدف: خطأ في سطر تشريح واحد لا يُسقط إثراء الكود بأكمله.
    """
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    items = []
    for entry in raw:
        try:
            item = model.model_validate(entry)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(item, AnatomyLine):
            if not item.explain.strip():
                continue
        elif isinstance(item, CodeUsage):
            if not (item.name.strip() and item.description.strip()):
                continue
        elif isinstance(item, ParamInfo):
            if not item.name.strip():
                continue
        items.append(item)
    return items


def _clean_text_list(raw: object) -> list[str]:
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    return [
        item.strip()
        for item in raw
        if isinstance(item, str) and item.strip()
    ]


def _merge_atlas(base: GeneratedCode, data: dict) -> GeneratedCode:
    """يدمج حقول الأطلس الصالحة فقط، ويُبقي الأصل عند فشل قسم واحد."""
    updates: dict[str, object] = {}
    for field, model in _LIST_FIELDS:
        items = _clean_items(data.get(field), model)
        if items:
            updates[field] = items
    for field in _TEXT_FIELDS:
        value = data.get(field)
        if isinstance(value, str) and value.strip():
            updates[field] = value.strip()
    for field in _TEXT_LIST_FIELDS:
        items = _clean_text_list(data.get(field))
        if items:
            updates[field] = items
    return GeneratedCode.model_validate({**base.model_dump(), **updates})
