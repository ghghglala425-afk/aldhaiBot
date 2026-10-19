# -*- coding: utf-8 -*-
"""اختبارات طبقة المزوّدين (Gemini / Groq / OpenRouter)."""
from __future__ import annotations

import datetime as dt
from unittest.mock import AsyncMock, Mock, patch

import pytest

from pipeline.providers import (
    ProviderSpec,
    _gemini_payload,
    _openai_payload,
    _parse_gemini,
    _parse_openai,
    _retry_after,
    build_providers,
)


class TestParsing:
    """تحليل استجابات المزوّدين."""

    def test_parse_gemini_ok(self) -> None:
        data = {
            "candidates": [{
                "content": {"parts": [{"text": "hello"}]}
            }],
            "usageMetadata": {"totalTokenCount": 42}
        }
        text, tokens = _parse_gemini(data)
        assert text == "hello"
        assert tokens == 42

    def test_parse_gemini_multipart(self) -> None:
        data = {
            "candidates": [{
                "content": {"parts": [{"text": "a"}, {"text": "b"}]}
            }],
            "usageMetadata": {"totalTokenCount": 10}
        }
        text, tokens = _parse_gemini(data)
        assert text == "ab"
        assert tokens == 10

    def test_parse_gemini_missing_usage(self) -> None:
        data = {"candidates": [{"content": {"parts": [{"text": "x"}]}}]}
        text, tokens = _parse_gemini(data)
        assert text == "x"
        assert tokens == 0

    def test_parse_openai_ok(self) -> None:
        data = {
            "choices": [{"message": {"content": "hello"}}],
            "usage": {"total_tokens": 25}
        }
        text, tokens = _parse_openai(data)
        assert text == "hello"
        assert tokens == 25

    def test_parse_openai_missing_usage(self) -> None:
        data = {"choices": [{"message": {"content": "y"}}]}
        text, tokens = _parse_openai(data)
        assert text == "y"
        assert tokens == 0


class TestRetryAfter:
    def test_retry_after_valid(self) -> None:
        resp = Mock()
        resp.headers = {"retry-after": "15"}
        assert _retry_after(resp) == 15.0

    def test_retry_after_invalid(self) -> None:
        resp = Mock()
        resp.headers = {"retry-after": "not-a-number"}
        assert _retry_after(resp) == 60.0

    def test_retry_after_missing(self) -> None:
        resp = Mock()
        resp.headers = {}
        assert _retry_after(resp) == 60.0


class TestPayloads:
    def test_gemini_payload_json_mode(self) -> None:
        payload = _gemini_payload(
            "sys", "usr", temperature=0.4, max_tokens=100, mode="json_object"
        )
        assert payload["generationConfig"]["responseMimeType"] == "application/json"
        assert payload["generationConfig"]["maxOutputTokens"] == 100

    def test_gemini_payload_no_json(self) -> None:
        payload = _gemini_payload(
            "sys", "usr", temperature=0.4, max_tokens=None, mode="none"
        )
        assert "responseMimeType" not in payload["generationConfig"]
        assert "maxOutputTokens" not in payload["generationConfig"]

    def test_openai_payload_json_mode(self) -> None:
        spec = ProviderSpec(
            name="test", base_url="x", model="m", api_key="k", json_object=True
        )
        payload = _openai_payload(spec, "sys", "usr", temperature=0.4, max_tokens=100, mode="json_object")
        assert payload["response_format"] == {"type": "json_object"}

    def test_openai_payload_no_json(self) -> None:
        spec = ProviderSpec(name="test", base_url="x", model="m", api_key="k", json_object=True)
        payload = _openai_payload(spec, "sys", "usr", temperature=0.4, max_tokens=None, mode="none")
        assert "response_format" not in payload


class TestProviderOrdering:
    """اختبارات ترتيب المزوّدين وتجاهل المفاتيح الفارغة."""

    def test_build_providers_order_and_empty(self) -> None:
        from core.config import Settings

        s = Settings(
            AI_FREE_MODE=True,
            GEMINI_API_KEY="k1",
            GEMINI_API_KEY_2="k2",
            GROQ_API_KEY="",
            OPENROUTER_API_KEY="",
            AI_PROVIDER_ORDER="groq,gemini,openrouter",
        )
        providers = build_providers(s)
        assert [p.name for p in providers] == ["gemini", "gemini"]
        assert providers[0].api_key == "k1"
        assert providers[1].api_key == "k2"

    def test_build_providers_skips_empty_keys(self) -> None:
        from core.config import Settings

        s = Settings(
            AI_FREE_MODE=True,
            GEMINI_API_KEY="",
            GROQ_API_KEY="g",
            OPENROUTER_API_KEY="",
            AI_PROVIDER_ORDER="gemini,groq,openrouter",
        )
        providers = build_providers(s)
        assert [p.name for p in providers] == ["groq"]


class TestGeminiPayload:
    def test_gemini_payload_sets_max_output(self) -> None:
        payload = _gemini_payload("s", "u", temperature=0.5, max_tokens=2048, mode="json_object")
        assert payload["generationConfig"]["maxOutputTokens"] == 2048

    def test_gemini_payload_json_object(self) -> None:
        payload = _gemini_payload("s", "u", temperature=0.5, max_tokens=None, mode="json_object")
        assert payload["generationConfig"]["responseMimeType"] == "application/json"

    def test_gemini_payload_none_mode(self) -> None:
        payload = _gemini_payload("s", "u", temperature=0.5, max_tokens=None, mode="none")
        assert "responseMimeType" not in payload["generationConfig"]