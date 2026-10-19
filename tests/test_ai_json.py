# -*- coding: utf-8 -*-
"""اختبارات توافق AI: استخراج JSON المتسامح + ترتيب أوضاع JSON."""
from __future__ import annotations

from core.config import settings
from pipeline.ai import extract_json


def test_extract_plain_object():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_from_code_fence():
    text = 'هذا هو الرد:\n```json\n{"title": "درس", "n": 3}\n```\nشكرا.'
    assert extract_json(text) == {"title": "درس", "n": 3}


def test_extract_with_preamble_and_trailing_text():
    text = 'بالطبع! {"items": [1, 2, 3]} وهذه نهاية الرد.'
    assert extract_json(text) == {"items": [1, 2, 3]}


def test_extract_nested_object():
    text = '```\n{"stages": [{"index": 1, "titles": ["أ", "ب"]}]}\n```'
    data = extract_json(text)
    assert data["stages"][0]["titles"] == ["أ", "ب"]


def test_extract_raises_on_garbage():
    try:
        extract_json("لا يوجد جيسون هنا إطلاقا")
    except ValueError:
        return
    raise AssertionError("كان يجب أن يفشل")


def test_json_mode_auto_order():
    saved = settings.AI_JSON_MODE
    try:
        settings.AI_JSON_MODE = "auto"
        assert settings.ai_json_modes == ["json_object", "json_schema", "none"]
        settings.AI_JSON_MODE = "json_object"
        assert settings.ai_json_modes == ["json_object", "none"]
        settings.AI_JSON_MODE = "none"
        assert settings.ai_json_modes == ["none"]
    finally:
        settings.AI_JSON_MODE = saved


def test_settings_defaults_for_local_model():
    assert settings.lessons_per_language == settings.GEN_STAGES * settings.GEN_LESSONS_PER_STAGE
    assert settings.lessons_per_language >= 1000
    assert settings.AI_MAX_TOKENS >= 1024
    assert settings.outline_model  # غير فارغ
