# -*- coding: utf-8 -*-
"""اختبارات رسائل أخطاء الذكاء الاصطناعي (موديل متقاعد/مفتاح/حصة)."""
from __future__ import annotations

from app.handlers.common import ai_error_text


class TestAiErrorText:
    def test_dead_model_mentions_fix(self) -> None:
        err = (
            "فشل كل المزوّدين: gemini: gemini: HTTP 404 {\"error\": {\"code\": 404, "
            "\"message\": \"This model is no longer available to new users\"}}"
        )
        text = ai_error_text(err)
        assert "gemini-3.5-flash-lite" in text
        assert "GEMINI_AUTODETECT" in text

    def test_all_models_rejected(self) -> None:
        text = ai_error_text("كل أسماء الموديلات مرفوضة: a | b | c")
        assert "GEMINI_MODEL" in text

    def test_invalid_key(self) -> None:
        text = ai_error_text("gemini: مفتاح غير صالح (401)")
        assert "GEMINI_API_KEY" in text

    def test_quota(self) -> None:
        text = ai_error_text("gemini: نفدت حصته اليومية")
        assert "حصة" in text

    def test_unknown_error_is_readable(self) -> None:
        text = ai_error_text("boom")
        assert "boom" in text
