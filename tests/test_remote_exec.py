# -*- coding: utf-8 -*-
"""تنفيذ خارجي (Piston): لا شيء يُشغَّل على المضيف."""
from __future__ import annotations

import asyncio
import base64
from unittest.mock import AsyncMock, patch

import pytest

from pipeline import sandbox_runner as sb
from pipeline.sandbox_runner import RunResult

RUNTIMES = [
    {"language": "python", "version": "3.10.0", "aliases": ["py"]},
    {"language": "javascript", "version": "18.15.0", "aliases": ["node"]},
    {"language": "c++", "version": "10.2.0", "aliases": ["cpp"]},
    {"language": "bash", "version": "5.2.0", "aliases": []},
]


class FakeResponse:
    def __init__(self, status_code: int = 200, data=None):
        self.status_code = status_code
        self._data = data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._data


class FakeClient:
    def __init__(self, *args, **kwargs):
        self.get_response = None
        self.get_responses = None
        self._get_index = 0
        self.post_response = None
        self.posted = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, *args, **kwargs):
        if self.get_responses is not None:
            index = min(self._get_index, len(self.get_responses) - 1)
            self._get_index += 1
            return self.get_responses[index]
        return self.get_response

    async def post(self, *args, **kwargs):
        self.posted = kwargs.get("json")
        return self.post_response


@pytest.fixture(autouse=True)
def _reset_state():
    sb._docker_state = None
    sb._remote_versions = None
    sb._judge0_state = None
    sb._remote_fail_until = 0.0
    yield
    sb._docker_state = None
    sb._remote_versions = None
    sb._judge0_state = None
    sb._remote_fail_until = 0.0


def test_remote_versions_mapping() -> None:
    client = FakeClient()
    client.get_response = FakeResponse(data=RUNTIMES)

    with (
        patch.object(sb.settings, "EXEC_API_URL", "https://piston.example"),
        patch.object(sb.httpx, "AsyncClient", lambda *a, **k: client),
    ):
        assert asyncio.run(sb.remote_available()) is True
        versions = asyncio.run(sb._piston_versions())
        assert versions["python"] == "3.10.0"
        assert versions["c++"] == "10.2.0"
        assert versions["cpp"] == "10.2.0"


def test_remote_execute_parses_output() -> None:
    client = FakeClient()
    client.get_response = FakeResponse(data=RUNTIMES)
    client.post_response = FakeResponse(
        data={"run": {"stdout": "hi\n", "stderr": "", "code": 0, "signal": None}}
    )

    async def _run():
        with (
            patch.object(sb.settings, "EXEC_API_URL", "https://piston.example"),
            patch.object(sb.httpx, "AsyncClient", lambda *a, **k: client),
        ):
            return await sb._run_remote("python", "print('hi')", 5)

    res = asyncio.run(_run())
    assert res.status == "ok"
    assert res.engine == "piston"
    assert res.stdout == "hi\n"


def test_remote_timeout_signal() -> None:
    client = FakeClient()
    client.get_response = FakeResponse(data=RUNTIMES)
    client.post_response = FakeResponse(
        data={"run": {"stdout": "", "stderr": "", "code": 137, "signal": "SIGKILL"}}
    )

    async def _run():
        with (
            patch.object(sb.settings, "EXEC_API_URL", "https://piston.example"),
            patch.object(sb.httpx, "AsyncClient", lambda *a, **k: client),
        ):
            return await sb._run_remote("python", "while True: pass", 1)

    res = asyncio.run(_run())
    assert res.status == "timeout"
    assert res.engine == "piston"


def test_remote_rate_limit_is_skipped() -> None:
    client = FakeClient()
    client.get_response = FakeResponse(data=RUNTIMES)
    client.post_response = FakeResponse(status_code=429)

    async def _run():
        with (
            patch.object(sb.settings, "EXEC_API_URL", "https://piston.example"),
            patch.object(sb.httpx, "AsyncClient", lambda *a, **k: client),
        ):
            return await sb._run_remote("python", "print(1)", 5)

    res = asyncio.run(_run())
    assert res.status == "skipped"
    assert "429" in res.detail


def test_run_code_prefers_remote_and_never_spawns_host() -> None:
    spawned: list[tuple] = []

    async def _fake_exec(*args, **kwargs):
        spawned.append(args)
        raise AssertionError("ممنوع تشغيل أي عملية على المضيف")

    async def _run():
        with (
            patch.object(sb, "remote_available", AsyncMock(return_value=True)),
            patch.object(
                sb, "_run_remote",
                AsyncMock(return_value=RunResult("ok", "piston", "ok\n")),
            ),
            patch.object(sb, "docker_available", AsyncMock(return_value=True)),
            patch("asyncio.create_subprocess_exec", _fake_exec),
        ):
            return await sb.run_code("python", "print('ok')", exec_enabled=True)

    res = asyncio.run(_run())
    assert res.status == "ok"
    assert res.engine == "piston"
    assert spawned == []


def test_available_languages_uses_remote_when_configured() -> None:
    async def _run():
        with (
            patch.object(sb, "remote_available", AsyncMock(return_value=True)),
            patch.object(
                sb, "_piston_versions",
                AsyncMock(return_value={"python": "3", "cpp": "10", "bash": "5"}),
            ),
            patch.object(sb, "docker_available", AsyncMock(return_value=False)),
        ):
            return await sb.available_languages()

    assert asyncio.run(_run()) == ["python", "bash", "cpp"]


def test_provider_autodetects_judge0() -> None:
    with patch.object(sb.settings, "EXEC_PROVIDER", ""):
        with patch.object(sb.settings, "EXEC_API_URL", "https://ce.judge0.com"):
            assert sb._provider() == "judge0"
        with patch.object(sb.settings, "EXEC_API_URL", "https://piston.example"):
            assert sb._provider() == "piston"


def _judge0_client(data, *, queued: bool = False) -> FakeClient:
    client = FakeClient()
    polls = [FakeResponse(data=data)]
    if queued:
        polls.insert(0, FakeResponse(data={"status": {"id": 1, "description": "In Queue"}}))
    client.get_responses = [FakeResponse(data=[]), *polls]
    client.post_response = FakeResponse(data={"token": "test-token"})
    return client


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def test_judge0_accepted() -> None:
    client = _judge0_client(
        {
            "stdout": _b64("4\n"),
            "stderr": None,
            "status": {"id": 3, "description": "Accepted"},
        },
        queued=True,
    )

    async def _run():
        with (
            patch.object(sb.settings, "EXEC_PROVIDER", "judge0"),
            patch.object(sb.settings, "EXEC_API_URL", "https://ce.judge0.com"),
            patch.object(sb.httpx, "AsyncClient", lambda *a, **k: client),
        ):
            return await sb.run_code("python", "print(2+2)", exec_enabled=True, timeout=5)

    res = asyncio.run(_run())
    assert res.status == "ok"
    assert res.engine == "judge0"
    assert res.stdout == "4\n"
    assert base64.b64decode(client.posted["source_code"]).decode() == "print(2+2)"


def test_judge0_time_limit() -> None:
    client = _judge0_client(
        {"stdout": None, "stderr": None, "status": {"id": 5, "description": "Time Limit Exceeded"}}
    )

    async def _run():
        with (
            patch.object(sb.settings, "EXEC_PROVIDER", "judge0"),
            patch.object(sb.settings, "EXEC_API_URL", "https://ce.judge0.com"),
            patch.object(sb.httpx, "AsyncClient", lambda *a, **k: client),
        ):
            return await sb.run_code("python", "while True: pass", exec_enabled=True, timeout=2)

    res = asyncio.run(_run())
    assert res.status == "timeout"
    assert res.engine == "judge0"


def test_judge0_compile_error() -> None:
    client = _judge0_client(
        {
            "stdout": None,
            "stderr": None,
            "compile_output": _b64("main.c:1: error: expected ';'"),
            "status": {"id": 6, "description": "Compilation Error"},
        }
    )

    async def _run():
        with (
            patch.object(sb.settings, "EXEC_PROVIDER", "judge0"),
            patch.object(sb.settings, "EXEC_API_URL", "https://ce.judge0.com"),
            patch.object(sb.httpx, "AsyncClient", lambda *a, **k: client),
        ):
            return await sb.run_code("c", "int main(){}", exec_enabled=True, timeout=5)

    res = asyncio.run(_run())
    assert res.status == "error"
    assert "error" in res.stderr
