# -*- coding: utf-8 -*-
"""سياسة الأمان: لا تنفيذ أكواد على المضيف — Docker فقط."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

from core.config import settings
from pipeline import sandbox_runner as sb

ROOT = Path(__file__).resolve().parents[1]


def test_no_local_execution_setting() -> None:
    assert not hasattr(settings, "SANDBOX_LOCAL"), "يجب ألا يوجد إعداد تنفيذ محلي"


def test_run_code_never_spawns_anything_without_docker() -> None:
    spawned: list[tuple] = []

    async def _fake_exec(*args, **kwargs):
        spawned.append(args)
        raise AssertionError("ممنوع تشغيل أي عملية على المضيف")

    with (
        patch.object(sb, "docker_available", AsyncMock(return_value=False)),
        patch("asyncio.create_subprocess_exec", _fake_exec),
    ):
        res = asyncio.run(sb.run_code("python", "print('x')", exec_enabled=True))

    assert res.status == "skipped"
    assert res.engine == "none"
    assert "Docker" in res.detail
    assert spawned == []


def test_available_languages_empty_without_docker() -> None:
    with patch.object(sb, "docker_available", AsyncMock(return_value=False)):
        assert asyncio.run(sb.available_languages()) == []


def test_sandbox_source_has_no_host_execution_path() -> None:
    src = (ROOT / "pipeline" / "sandbox_runner.py").read_text(encoding="utf-8")
    for token in ("SANDBOX_LOCAL", "_local_cmd", "local_languages", "_safe_env", '"local"'):
        assert token not in src, f"بقايا تنفيذ محلي: {token}"


class TestCleanCode:
    """الكود المنسوخ من الدرس غالبا يحمل أسوار Markdown فتظهر أخطاء صياغة."""

    def test_strips_markdown_fence_with_language(self) -> None:
        assert sb.clean_code("```python\nprint('hi')\n```") == "print('hi')"

    def test_strips_bare_fence(self) -> None:
        assert sb.clean_code("```\nprint('hi')\n```") == "print('hi')"

    def test_keeps_plain_code_untouched(self) -> None:
        code = "for p in [22, 80]:\n    print(p)"
        assert sb.clean_code(code) == code

    def test_removes_invisible_chars_and_crlf(self) -> None:
        assert sb.clean_code("\ufeffprint('a')\r\nprint('b')\u200f") == "print('a')\nprint('b')"

    def test_empty_after_cleaning_is_skipped(self) -> None:
        res = asyncio.run(sb.run_code("python", "   \n", exec_enabled=True))
        assert res.status == "skipped"

    def test_fenced_code_reaches_runner_clean(self) -> None:
        seen: list[str] = []

        async def _fake_run_once(runner, language, code, timeout):
            seen.append(code)
            return sb.RunResult("ok", "judge0", "hi\n", "")

        with (
            patch.object(sb, "_run_once", _fake_run_once),
            patch.object(sb, "_transient", lambda res: False),
        ):
            res = asyncio.run(
                sb.run_code("python", "```python\nprint('hi')\n```", exec_enabled=True)
            )

        assert res.status == "ok"
        assert seen == ["print('hi')"]
