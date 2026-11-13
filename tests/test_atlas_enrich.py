# -*- coding: utf-8 -*-
"""إثراء موسوعة الأكواد: مرادفات أسماء الحقول، ودمج الأقسام الصالحة فقط."""
from __future__ import annotations

import asyncio

from pipeline import atlas
from pipeline.schema import AnatomyLine, CodeUsage, GeneratedCode, ParamInfo


def _base_code() -> GeneratedCode:
    return GeneratedCode(
        language="python",
        title="مثال الطباعة",
        code="print('hi')\nprint('bye')",
        explanation="مثال يوضّح الطباعة.",
        expected_output="hi\nbye",
        anatomy=[AnatomyLine(line=1, code="print('hi')", explain="اطبع نصا.")],
    )


def test_anatomy_accepts_explanation_aliases():
    variants = [
        {"line": 1, "code": "a = 1", "explanation": "تعريف متغير."},
        {"line": 2, "code": "b = 2", "desc": "تعريف ثان."},
        {"line": 3, "code": "c = 3", "description": "تعريف ثالث."},
        {"line": 4, "code": "d = 4", "شرح": "تعريف رابع."},
    ]
    lines = [AnatomyLine.model_validate(item) for item in variants]
    assert [ln.explain for ln in lines] == [
        "تعريف متغير.",
        "تعريف ثان.",
        "تعريف ثالث.",
        "تعريف رابع.",
    ]
    assert [ln.line for ln in lines] == [1, 2, 3, 4]


def test_anatomy_does_not_fail_on_missing_explain():
    line = AnatomyLine.model_validate({"line": 1, "code": "x = 1"})
    assert line.code == "x = 1"
    assert line.explain == ""


def test_code_usage_accepts_aliases():
    usage = CodeUsage.model_validate(
        {
            "title": "print",
            "syntax": "print(value)",
            "desc": "تطبع القيمة.",
            "code": "print(1)",
            "result": "1",
        }
    )
    assert usage.name == "print"
    assert usage.signature == "print(value)"
    assert usage.description == "تطبع القيمة."
    assert usage.example == "print(1)"
    assert usage.output == "1"


def test_param_info_accepts_aliases():
    param = ParamInfo.model_validate(
        {"parameter": "value", "datatype": "Any", "desc": "القيمة.", "required": "true"}
    )
    assert param.name == "value"
    assert param.type == "Any"
    assert param.description == "القيمة."
    assert param.required is True


def test_clean_items_skips_broken_entries_only():
    raw = [
        {"line": 1, "code": "x = 1", "explanation": "تعريف."},
        {"line": 2, "code": "y = 2"},  # بلا شرح ولا فائدة
        "نص حر",  # يُقبل كنص سطر
    ]
    items = atlas._clean_items(raw, AnatomyLine)
    assert len(items) == 2
    assert isinstance(items[0], AnatomyLine)


def test_merge_keeps_base_when_one_section_is_broken():
    base = _base_code()
    merged = atlas._merge_atlas(
        base,
        {
            "anatomy": [{"line": 1, "code": "x = 1", "explanation": "تعريف متغير."}],
            "usages": "ليست قائمة",
            "parameters": [{"type": "int"}],  # بلا اسم → يُستبعد
            "returns": "لا شيء",
            "gotchas": ["خطأ شائع"],
            "tags": "python",
        },
    )
    assert merged.anatomy and merged.anatomy[0].explain == "تعريف متغير."
    # قسم معطوب يُبقي نسخة الأساس بدل إسقاط الإثراء كله
    assert merged.usages == base.usages
    assert merged.parameters == base.parameters
    assert merged.returns == "لا شيء"
    assert merged.gotchas == ["خطأ شائع"]
    assert merged.tags == ["python"]


def test_merge_with_model_style_keys_never_drops_the_code(monkeypatch):
    code = _base_code()

    async def fake_batch(codes, language):
        return {
            1: {
                "anatomy": [
                    {"line": 1, "code": "print('hi')", "explanation": "تطبع تحية."},
                    {"line": 2, "code": "print('bye')", "شرح": "تطبع وداعا."},
                ],
                "usages": [
                    {
                        "title": "print",
                        "syntax": "print(value)",
                        "desc": "تطبع قيمة.",
                        "code": "print(1)",
                        "result": "1",
                    }
                ],
                "parameters": [{"parameter": "value", "desc": "القيمة.", "required": "true"}],
                "returns": "تطبع فقط.",
                "gotchas": ["نسيان الأقواس"],
            }
        }

    monkeypatch.setattr(atlas, "_enrich_batch", fake_batch)
    result = asyncio.run(atlas.enrich_codes([code], "python", batch_size=4))
    assert len(result) == 1
    enriched = result[0]
    assert len(enriched.anatomy) == 2
    assert enriched.anatomy[0].explain == "تطبع تحية."
    assert enriched.usages[0].name == "print"
    assert enriched.parameters[0].name == "value"
    assert enriched.parameters[0].required is True
    assert enriched.returns == "تطبع فقط."
    assert enriched.gotchas == ["نسيان الأقواس"]


def test_enrich_batch_normalizes_zero_based_index(monkeypatch):
    async def fake_chat(system, user, **kwargs):
        return {"items": [{"index": 0, "returns": "أ"}]}

    monkeypatch.setattr(atlas, "chat_json", fake_chat)
    code = _base_code()
    out = asyncio.run(atlas._enrich_batch([code], "python"))
    assert out == {1: {"index": 0, "returns": "أ"}}
