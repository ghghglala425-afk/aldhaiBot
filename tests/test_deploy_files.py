# -*- coding: utf-8 -*-
"""اختبارات سلامة ملفات النشر — تمنع مراجع مكسورة.

الهدف: التقاط أخطاء مثل `celery -A pipeline.celery_app` بينما الملف غير موجود،
أو `platform: linux/arm64` مثبّت يكسر البناء على x86.
"""
from __future__ import annotations

import re
import shlex
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


class TestNoBom:
    """BOM يكسر محلّل JSON في Railway (serde_json يرفضه)."""

    BOM = b"\xef\xbb\xbf"

    def _has_bom(self, rel: str) -> bool:
        path = ROOT / rel
        if not path.is_file():
            return False
        return path.read_bytes().startswith(self.BOM)

    def test_railway_json_has_no_bom(self) -> None:
        for name in ("railway.json", "railway.api.json"):
            assert not self._has_bom(name), f"{name} starts with a BOM - Railway cannot parse it"

    def test_compose_yml_has_no_bom(self) -> None:
        for name in ("docker-compose.yml", "docker-compose.prod.yml"):
            assert not self._has_bom(name), f"{name} starts with a BOM"

    def test_dockerfile_has_no_bom(self) -> None:
        for name in ("Dockerfile", "Dockerfile.prod"):
            assert not self._has_bom(name), f"{name} starts with a BOM"

    def test_powershell_scripts_keep_bom(self) -> None:
        """سكربتات PowerShell تحتاج BOMEncodeenc لعرض العربية في PS 5.1."""
        for name in ("run_bot.ps1", "run_forever.ps1", "install_autostart.ps1", "backup_db.ps1"):
            path = ROOT / name
            if not path.is_file():
                continue
            assert path.read_bytes().startswith(self.BOM), (
                f"{name} lost its BOM - Arabic text breaks in Windows PowerShell 5.1"
            )

    def test_json_files_parse_without_bom(self) -> None:
        import json

        for name in ("railway.json", "railway.api.json"):
            with (ROOT / name).open(encoding="utf-8") as fh:
                json.load(fh)


class TestNoBrokenModuleReferences:
    """كل `python -m x.y` يجب أن ي对应 ملفا موجودا."""

    def test_python_m_targets_exist(self) -> None:
        pattern = re.compile(r"python(?:3)?\s+-m\s+([\w.]+)")
        for name in (
            "Dockerfile",
            "Dockerfile.prod",
            "docker-compose.yml",
            "docker-compose.prod.yml",
            "scripts/entrypoint.sh",
            "run_bot.ps1",
        ):
            path = ROOT / name
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            for module in pattern.findall(text):
                rel = module.replace(".", "/")
                if not (ROOT / f"{rel}.py").exists() and not (ROOT / rel).is_dir():
                    raise AssertionError(f"{name} references missing module '{module}'")

    def test_celery_app_is_not_referenced(self) -> None:
        """عامل التوليد يعمل داخل البوت — لا حاجة لـ Celery."""
        for name in ("Dockerfile.prod", "docker-compose.prod.yml", "railway.json",
                     "railway.api.json", "docker-compose.yml"):
            path = ROOT / name
            if not path.is_file():
                continue
            # نتجاهل التعليقات — الشرح النصي غير مؤثر
            code = "\n".join(
                ln for ln in path.read_text(encoding="utf-8").splitlines()
                if not ln.strip().startswith("#")
            )
            assert "celery" not in code.lower(), f"{name} still references celery"

    def test_celery_is_not_a_dependency(self) -> None:
        reqs = _read("requirements.txt").lower()
        assert "celery" not in reqs


class TestNoHardcodedPlatform:
    """`--platform=linux/arm64` يكسر البناء على معالج x86."""

    def test_no_platform_pinned_in_dockerfiles(self) -> None:
        for name in ("Dockerfile", "Dockerfile.prod"):
            text = _read(name)
            assert "--platform=" not in text, f"{name} pins a platform"

    def test_no_platform_pinned_in_compose(self) -> None:
        for name in ("docker-compose.yml", "docker-compose.prod.yml"):
            text = _read(name)
            assert "platform: linux/arm64" not in text, f"{name} pins arm64"


class TestComposeValidity:
    def test_prod_compose_has_no_worker_service(self) -> None:
        text = _read("docker-compose.prod.yml")
        assert "\n  worker:" not in text

    def test_prod_compose_services(self) -> None:
        text = _read("docker-compose.prod.yml")
        for svc in ("db:", "redis:", "api:", "bot:", "nginx:", "certbot:"):
            assert f"\n  {svc}" in text, f"missing service {svc}"

    def test_compose_commands_use_entrypoint(self) -> None:
        text = _read("docker-compose.prod.yml")
        assert "scripts/entrypoint.sh" in text

    def test_compose_db_credentials_are_env_driven(self) -> None:
        text = _read("docker-compose.prod.yml")
        assert "${DB_PASSWORD}" in text

    def test_nginx_mounts_exist(self) -> None:
        text = _read("docker-compose.prod.yml")
        for mount in ("./nginx.conf", "./certbot/conf", "./certbot/www"):
            assert mount in text, f"missing mount {mount}"


class TestPortHandling:
    """كل خدمة HTTP يجب أن تسمع على $PORT."""

    def test_dockerfiles_use_port_fallback(self) -> None:
        for name in ("Dockerfile", "Dockerfile.prod"):
            assert "${PORT:-8000}" in _read(name), f"{name} must honour $PORT"

    def test_entrypoint_uses_port(self) -> None:
        assert "${PORT:-8000}" in _read("scripts/entrypoint.sh")

    def test_no_hardcoded_port_8000_in_commands(self) -> None:
        """أوامر التشغيل يجب أن تستعمل $PORT لا 8000."""
        for name in ("docker-compose.prod.yml", "railway.json", "railway.api.json"):
            text = _read(name)
            for line in text.splitlines():
                if "command" in line or "startCommand" in line:
                    assert "--port 8000" not in line, f"{name}: {line.strip()}"


class TestEntrypointRoles:
    def test_entrypoint_is_referenced_by_both_configs(self) -> None:
        assert "entrypoint.sh" in _read("railway.json")
        assert "entrypoint.sh" in _read("railway.api.json")

    def test_api_role_uses_api_role_env(self) -> None:
        assert "APP_ROLE=api" in _read("railway.api.json")

    def test_default_role_is_bot(self) -> None:
        assert 'APP_ROLE:-bot' in _read("scripts/entrypoint.sh")
