# -*- coding: utf-8 -*-
"""اختبار سلامة سجلّ اللغات."""
from pipeline.languages_data import LANGUAGES


def test_languages_unique_slugs():
    slugs = [x["slug"] for x in LANGUAGES]
    assert len(slugs) == len(set(slugs)), "توجد لغة مكررة"


def test_languages_have_required_fields():
    for x in LANGUAGES:
        assert x.get("slug") and x.get("name")
        assert x.get("difficulty") in {"easy", "medium", "hard"}
