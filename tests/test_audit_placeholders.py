# -*- coding: utf-8 -*-
"""كاشف النصوص البديلة في تدقيق الإنتاج: يمسك العلامات الحقيقية فقط."""
from __future__ import annotations

import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "audit_prod.py"
_spec = importlib.util.spec_from_file_location("audit_prod_for_tests", _PATH)
audit = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(audit)

PLACEHOLDERS = audit.PLACEHOLDERS


def test_technical_terms_in_real_lessons_are_not_placeholders():
    legit = [
        "**Placeholder** وهو مكان مخصص في الاستعلام يتم ملؤه لاحقاً.",
        "استخدم المعاملات (Placeholders) بدل دمج النصوص.",
        "القيمة المفقودة undefined — والصيغة الأخرى null.",
        "خاصية `placeholder` في HTML تعرض نصا إرشاديا.",
        "قريبا سنتعلم المزيد عن هذا الموضوع.",
    ]
    for text in legit:
        assert not PLACEHOLDERS.search(text), text


def test_real_placeholder_markers_are_detected():
    bad = [
        "TODO: أكمل هذا القسم",
        "هذا شرح مؤقت FIXME",
        "(Placeholder)",
        "undefined",
        "[TODO]",
        "lorem ipsum dolor sit amet",
        "سيتم إضافة أمثلة لاحقا",
        "(قريبا)",
    ]
    for text in bad:
        assert PLACEHOLDERS.search(text), text
