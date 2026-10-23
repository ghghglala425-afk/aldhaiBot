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

    def test_retry_after_from_google_body(self) -> None:
        resp = Mock()
        resp.headers = {}
        resp.json.return_value = {
            "error": {
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.RetryInfo",
                        "retryDelay": "10800s",
                    }
                ]
            }
        }
        assert _retry_after(resp) == 10800.0


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
            GEMINI_API_KEYS="",
            GEMINI_API_KEY="k1",
            GEMINI_API_KEY_2="k2",
            GROQ_API_KEYS="",
            GROQ_API_KEY="",
            OPENROUTER_API_KEYS="",
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
            GEMINI_API_KEYS="",
            GEMINI_API_KEY="",
            GROQ_API_KEYS="",
            GROQ_API_KEY="g",
            OPENROUTER_API_KEYS="",
            OPENROUTER_API_KEY="",
            AI_PROVIDER_ORDER="gemini,groq,openrouter",
        )
        providers = build_providers(s)
        assert [p.name for p in providers] == ["groq"]

    def test_build_providers_many_gemini_keys(self) -> None:
        from core.config import Settings

        s = Settings(
            AI_FREE_MODE=True,
            GEMINI_API_KEYS="k1, k2;k3\nk1",
            GEMINI_API_KEY="",
            GEMINI_API_KEY_2="",
            AI_PROVIDER_ORDER="gemini",
        )
        providers = build_providers(s)
        assert [p.api_key for p in providers] == ["k1", "k2", "k3"]
        assert len({p.key_id for p in providers}) == 3

    def test_build_providers_extra_openai_compatible(self) -> None:
        from core.config import Settings

        s = Settings(
            AI_FREE_MODE=True,
            GEMINI_API_KEYS="",
            GEMINI_API_KEY="",
            GEMINI_API_KEY_2="",
            GROQ_API_KEYS="",
            GROQ_API_KEY="",
            OPENROUTER_API_KEYS="",
            OPENROUTER_API_KEY="",
            EXTRA_AI_NAME="cerebras",
            EXTRA_AI_BASE_URL="https://api.cerebras.ai/v1",
            EXTRA_AI_MODEL="llama-3.3-70b",
            EXTRA_AI_API_KEYS="e1,e2",
            AI_PROVIDER_ORDER="gemini,groq,openrouter,extra",
        )
        providers = build_providers(s)
        assert [p.name for p in providers] == ["cerebras", "cerebras"]
        assert [p.api_key for p in providers] == ["e1", "e2"]
        assert providers[0].native is False
        assert providers[0].base_url == "https://api.cerebras.ai/v1"


class TestPerKeyState:
    def test_usage_is_isolated_per_key(self, monkeypatch) -> None:
        import asyncio
        from types import SimpleNamespace

        from pipeline import providers as p

        rows: dict[str, SimpleNamespace] = {}

        async def fake_usage_row(session, provider):
            return rows.setdefault(
                provider, SimpleNamespace(requests=0, tokens=0, errors=0)
            )

        async def no_budget(session):
            return None

        monkeypatch.setattr(p, "_usage_row", fake_usage_row)
        monkeypatch.setattr(p, "_budget_left", no_budget)

        a = p.ProviderSpec("gemini", "x", "m", "keyAAAAAA", rpd=1)
        b = p.ProviderSpec("gemini", "x", "m", "keyBBBBBB", rpd=1)
        rows[a.key_id] = SimpleNamespace(requests=1, tokens=0, errors=0)

        assert asyncio.run(p._can_call(None, a)) is False
        assert asyncio.run(p._can_call(None, b)) is True

    def test_cooldown_is_shared_across_specs(self, monkeypatch) -> None:
        from pipeline import providers as p

        monkeypatch.setattr(p, "_COOLDOWNS", {}, raising=False)
        a = p.ProviderSpec("gemini", "x", "m", "same-key-123")
        b = p.ProviderSpec("gemini", "x", "m", "same-key-123")
        a.cool(60)
        assert a.ready() is False
        assert b.ready() is False


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


class TestModelChain:
    def test_settings_chain_dedup_and_order(self) -> None:
        from core.config import Settings

        s = Settings(
            GEMINI_MODEL="a",
            GEMINI_MODEL_CHAIN="a,b",
            GEMINI_FALLBACK_MODEL="c",
        )
        assert s.gemini_models == ["a", "b", "c"]

    def test_rank_prefers_text_flash_lite(self) -> None:
        from pipeline.providers import _rank_models

        ranked = _rank_models(
            [
                "gemini-2.5-flash-image",
                "gemini-3.8-flash-tts",
                "gemini-3.8-flash",
                "gemini-3.5-flash-lite",
                "gemini-3.1-flash-lite",
            ]
        )
        assert ranked[0] == "gemini-3.5-flash-lite"
        assert "gemini-3.8-flash-tts" in ranked
        assert "gemini-2.5-flash-image" in ranked
        assert ranked.index("gemini-3.8-flash") < ranked.index("gemini-2.5-flash-image")

    def test_model_error_detection(self) -> None:
        from pipeline.providers import ProviderError, _is_model_error

        assert _is_model_error(ProviderError("gemini: HTTP 404 no longer available"))
        assert _is_model_error(ProviderError("model not supported"))
        assert not _is_model_error(ProviderError("gemini: مفتاح غير صالح (401)"))
        assert not _is_model_error(ProviderError("تجاوز الحد (429)"))


class TestModelFailover:
    @pytest.fixture(autouse=True)
    def _isolate(self, monkeypatch):
        from pipeline import providers as p

        monkeypatch.setattr(p, "_chosen_model", {}, raising=False)
        monkeypatch.setattr(p, "_model_cache", {}, raising=False)
        monkeypatch.setattr(p.settings, "GEMINI_AUTODETECT", False, raising=False)
        return p

    def _spec(self, p, model: str = "gemini-2.5-flash-lite"):
        return p.ProviderSpec(
            name="gemini",
            base_url="https://example.invalid/v1beta",
            model=model,
            api_key="abc1234",
            native=True,
        )

    def test_dead_model_switches_to_next(self, monkeypatch) -> None:
        import asyncio

        from pipeline import providers as p

        calls: list[str] = []

        async def fake_call(spec, system, user, **kwargs):
            calls.append(spec.model)
            if spec.model.startswith("gemini-2.5"):
                raise p.ProviderError(
                    f"{spec.name}: HTTP 404 no longer available to new users"
                )
            return "ok", 7

        async def no_discovery(spec):
            return []

        monkeypatch.setattr(p, "_call_one", fake_call)
        monkeypatch.setattr(p, "_discover_models", no_discovery)
        spec = self._spec(p)
        text, tokens = asyncio.run(
            p._call_with_fallback(
                spec, "s", "u", temperature=0.0, max_tokens=None, mode="none"
            )
        )
        assert (text, tokens) == ("ok", 7)
        assert calls[0] == "gemini-2.5-flash-lite"
        assert calls[1] == "gemini-3.5-flash-lite"
        assert spec.model == "gemini-3.5-flash-lite"
        assert p._chosen_model[spec.key_id] == "gemini-3.5-flash-lite"

    def test_discovered_model_is_used(self, monkeypatch) -> None:
        import asyncio

        from pipeline import providers as p

        calls: list[str] = []

        async def fake_call(spec, system, user, **kwargs):
            calls.append(spec.model)
            if spec.model.startswith("gemini-2.5"):
                raise p.ProviderError(f"{spec.name}: HTTP 404 not found")
            if spec.model == "gemini-9.9-ultra":
                return "from-discovery", 3
            raise p.ProviderError(f"{spec.name}: HTTP 404 not found")

        async def fake_discovery(spec):
            return ["gemini-9.9-ultra"]

        monkeypatch.setattr(p.settings, "GEMINI_AUTODETECT", True)
        monkeypatch.setattr(p, "_call_one", fake_call)
        monkeypatch.setattr(p, "_discover_models", fake_discovery)
        spec = self._spec(p)
        text, _ = asyncio.run(
            p._call_with_fallback(
                spec, "s", "u", temperature=0.0, max_tokens=None, mode="none"
            )
        )
        assert text == "from-discovery"
        assert "gemini-9.9-ultra" in calls

    def test_non_model_error_is_not_retried(self, monkeypatch) -> None:
        import asyncio

        from pipeline import providers as p

        calls: list[str] = []

        async def fake_call(spec, system, user, **kwargs):
            calls.append(spec.model)
            raise p.ProviderError(f"{spec.name}: مفتاح غير صالح (401)")

        monkeypatch.setattr(p, "_call_one", fake_call)
        with pytest.raises(p.ProviderError):
            asyncio.run(
                p._call_with_fallback(
                    self._spec(p), "s", "u",
                    temperature=0.0, max_tokens=None, mode="none",
                )
            )
        assert calls == ["gemini-2.5-flash-lite"]

    def test_transient_error_retried_once(self, monkeypatch) -> None:
        import asyncio

        from pipeline import providers as p

        calls: list[str] = []

        async def fake_call(spec, system, user, **kwargs):
            calls.append(spec.model)
            if len(calls) == 1:
                raise p.ProviderError(f"{spec.name}: HTTP 503 service unavailable")
            return "recovered", 2

        async def no_discovery(spec):
            return []

        monkeypatch.setattr(p, "_call_one", fake_call)
        monkeypatch.setattr(p, "_discover_models", no_discovery)
        text, tokens = asyncio.run(
            p._call_with_fallback(
                self._spec(p), "s", "u",
                temperature=0.0, max_tokens=None, mode="none",
            )
        )
        assert (text, tokens) == ("recovered", 2)
        assert len(calls) == 2

    def test_all_models_fail_reports_names(self, monkeypatch) -> None:
        import asyncio

        from pipeline import providers as p

        async def fake_call(spec, system, user, **kwargs):
            raise p.ProviderError(f"{spec.name}: HTTP 404 not found")

        async def no_discovery(spec):
            return []

        monkeypatch.setattr(p, "_call_one", fake_call)
        monkeypatch.setattr(p, "_discover_models", no_discovery)
        with pytest.raises(p.ProviderError) as exc:
            asyncio.run(
                p._call_with_fallback(
                    self._spec(p), "s", "u",
                    temperature=0.0, max_tokens=None, mode="none",
                )
            )
        assert "كل أسماء الموديلات مرفوضة" in str(exc.value)
