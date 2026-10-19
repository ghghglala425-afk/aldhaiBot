# -*- coding: utf-8 -*-
"""اختبارات Dockerfile و dockerignore — تمنع أخطاء البناء على Railway.

الهدف: التقاط أخطاء مثل `RUN chmod` بعد `USER` (تفشل بصلاحية غير كافية)
أو استبعاد ملف يدخله Dockerfile من سياق البناء.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _dockerfile() -> str:
    return (ROOT / "Dockerfile").read_text(encoding="utf-8")


def _dockerignore_patterns() -> list[str]:
    lines = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


class TestDockerfileOrder:
    """ترتيب التعليمات مهم: chmod/chown يجب أن يكونا قبل تبديل المستخدم."""

    def test_code_is_copied_before_user_switch(self) -> None:
        df = _dockerfile()
        assert df.index("COPY . .") < df.index("USER appuser")

    def test_chown_before_user_switch(self) -> None:
        df = _dockerfile()
        assert df.index("chown -R appuser:appuser /app") < df.index("USER appuser")

    def test_entrypoint_does_not_need_exec_bit(self) -> None:
        """الاستدعاء عبر `sh` فلا نحتاج chmod — أخطاء الصلاحيات تفشل البناء."""
        df = _dockerfile()
        assert "scripts/entrypoint.sh" in df
        assert "chmod +x /app/scripts/entrypoint.sh" not in df, (
            "chmod on a root-owned file after USER breaks the build"
        )

    def test_cmd_falls_back_when_entrypoint_missing(self) -> None:
        """إن لم يوجد السكربت في الصورة نشغّل البوت مباشرة (لا تنكسر الحاوية)."""
        df = _dockerfile()
        assert "python -m app.bot" in df.split("CMD")[-1], "CMD needs a bot fallback"

    def test_requirements_copied_before_pip_install(self) -> None:
        df = _dockerfile()
        assert df.index("COPY requirements.txt .") < df.index("pip install -r requirements.txt")


class TestDockerfileContent:
    def test_entrypoint_is_referenced_by_cmd(self) -> None:
        assert "scripts/entrypoint.sh" in _dockerfile()

    def test_curl_is_installed_for_healthcheck(self) -> None:
        df = _dockerfile()
        assert "curl" in df.split("HEALTHCHECK")[0], "curl must be installed before HEALTHCHECK"

    def test_healthcheck_uses_port_variable(self) -> None:
        df = _dockerfile()
        assert "PORT:-8000" in df

    def test_base_image_is_python_slim(self) -> None:
        from_lines = [
            ln.strip()
            for ln in _dockerfile().splitlines()
            if ln.strip().upper().startswith("FROM ")
        ]
        assert from_lines, "Dockerfile has no FROM instruction"
        assert from_lines[0].split()[1] == "python:3.12-slim"

    def test_non_root_user_is_used(self) -> None:
        assert "USER appuser" in _dockerfile()

    def test_docker_cli_is_optional(self) -> None:
        df = _dockerfile()
        assert "ARG INSTALL_DOCKER_CLI=0" in df


class TestEntrypoint:
    def test_entrypoint_exists(self) -> None:
        assert (ROOT / "scripts" / "entrypoint.sh").is_file()

    def test_entrypoint_has_both_roles(self) -> None:
        text = (ROOT / "scripts" / "entrypoint.sh").read_text(encoding="utf-8")
        assert "APP_ROLE" in text
        assert "python -m app.bot" in text
        assert "uvicorn api.main:app" in text

    def test_entrypoint_uses_port_variable(self) -> None:
        text = (ROOT / "scripts" / "entrypoint.sh").read_text(encoding="utf-8")
        assert "${PORT:-8000}" in text

    def test_entrypoint_is_valid_shell(self) -> None:
        """فحص بناء الجملة: كل的命令 تنتهي بـ ; أو \\."""
        text = (ROOT / "scripts" / "entrypoint.sh").read_text(encoding="utf-8")
        assert text.startswith("#!/bin/sh")
        assert "set -e" in text
        # كل سطر غير فارغ يجب أن يكون أمرا صالحا
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            assert re.match(r"^[A-Za-z_\[\(].*", line), f"bad shell line: {line!r}"


class TestDockerignore:
    def test_entrypoint_is_not_ignored(self) -> None:
        patterns = _dockerignore_patterns()
        assert "scripts/entrypoint.sh" not in patterns
        assert "scripts/" not in patterns

    def test_env_is_ignored(self) -> None:
        patterns = _dockerignore_patterns()
        assert ".env" in patterns

    def test_venv_is_ignored(self) -> None:
        patterns = _dockerignore_patterns()
        assert any(p.startswith(".venv") for p in patterns)

    def test_data_is_ignored(self) -> None:
        patterns = _dockerignore_patterns()
        assert "data/" in patterns


class TestRailwayConfigs:
    def test_railway_json_exists_and_is_valid(self) -> None:
        import json

        data = json.loads((ROOT / "railway.json").read_text(encoding="utf-8"))
        assert data["build"]["builder"] == "DOCKERFILE"
        assert "entrypoint" in data["deploy"]["startCommand"]

    def test_railway_api_json_uses_api_role(self) -> None:
        import json

        data = json.loads((ROOT / "railway.api.json").read_text(encoding="utf-8"))
        assert "APP_ROLE=api" in data["deploy"]["startCommand"]

    def test_healthcheck_path_is_health(self) -> None:
        import json

        for name in ("railway.json", "railway.api.json"):
            data = json.loads((ROOT / name).read_text(encoding="utf-8"))
            assert data["deploy"]["healthcheckPath"] == "/health"

    def test_single_replica(self) -> None:
        """نسختان في Polling = تعارض تيليجرام."""
        import json

        data = json.loads((ROOT / "railway.json").read_text(encoding="utf-8"))
        assert data["deploy"]["numReplicas"] == 1
