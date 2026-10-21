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
