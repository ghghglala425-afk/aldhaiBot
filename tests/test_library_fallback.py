# -*- coding: utf-8 -*-
"""البديل المحلي للمساعد: إجابة من مكتبة الأكاديمية عند نفاد حصص AI."""
from __future__ import annotations

from app.handlers.assistant import _keywords, _variants


class TestKeywords:
    def test_drops_stopwords_and_short_words(self) -> None:
        words = _keywords("ما هو المنفذ 443 وكيف يعمل؟")
        assert "المنفذ" in words
        assert "443" in words
        assert "ما" not in words
        assert "هو" not in words

    def test_limits_terms(self) -> None:
        words = _keywords(" ".join(f"كلمة{i}" for i in range(20)))
        assert len(words) == 6

    def test_empty_question(self) -> None:
        assert _keywords("؟؟؟") == []


class TestVariants:
    def test_strips_arabic_definite_article(self) -> None:
        assert _variants("المنفذ") == ["المنفذ", "منفذ"]

    def test_keeps_plain_terms(self) -> None:
        assert _variants("sql") == ["sql"]

    def test_short_words_untouched(self) -> None:
        assert _variants("الي") == ["الي"]
