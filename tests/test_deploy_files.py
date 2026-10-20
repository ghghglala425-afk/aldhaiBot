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


class TestTokenValidation:
    """توكن غير صالح = كل النداءات تفشل وتغمر سجلات Railway."""

    def test_token_is_validated_before_polling(self) -> None:
        src = (ROOT / "app" / "bot.py").read_text(encoding="utf-8")
        assert "_validate_token" in src
        run_body = src.split("def _run()")[1]
        assert "_validate_token()" in run_body

    def test_invalid_token_does_not_start_polling(self) -> None:
        src = (ROOT / "app" / "bot.py").read_text(encoding="utf-8")
        run_body = src.split("def _run()")[1].split("def _idle_loop")[0]
        # التحقق يسبق run_polling
        assert run_body.index("_validate_token()") < run_body.index("run_polling")

    def test_health_server_starts_before_token_check(self) -> None:
        """الخادم الصحي أولا وإلا فشل فحص Railway عند رفض التوكن."""
        src = (ROOT / "app" / "bot.py").read_text(encoding="utf-8")
        run_body = src.split("def _run()")[1].split("def _idle_loop")[0]
        assert run_body.index("_start_health_server") < run_body.index("_validate_token()")

    def test_diag_reports_token_validity(self) -> None:
        src = (ROOT / "app" / "bot.py").read_text(encoding="utf-8")
        assert '"token_valid"' in src
        assert '"token_error"' in src


class TestLogThrottling:
    """Railway يحذف الرسائل بعد 500/ثانية."""

    def test_throttle_filter_exists(self) -> None:
        src = (ROOT / "core" / "logging.py").read_text(encoding="utf-8")
        assert "_ThrottleFilter" in src

    def test_throttle_filter_is_applied(self) -> None:
        src = (ROOT / "core" / "logging.py").read_text(encoding="utf-8")
        assert src.count("addFilter(_ThrottleFilter())") >= 1

    def test_railway_mode_is_polling(self) -> None:
        """Webhook لا يعمل خلف proxy Railway."""
        src = (ROOT / "app" / "bot.py").read_text(encoding="utf-8")
        assert "RAILWAY_ENVIRONMENT" in src
        assert 'settings.BOT_MODE = "polling"' in src


class TestDiagnosticEndpoint:
    """/diag يجعل النشر الفاشل قابلا للتشخيص عبر المتصفح."""

    def test_health_server_offers_diag(self) -> None:
        src = (ROOT / "app" / "bot.py").read_text(encoding="utf-8")
        assert '"/diag"' in src
        assert '"/health"' in src

    def test_diag_reports_errors_and_warnings(self) -> None:
        src = (ROOT / "app" / "bot.py").read_text(encoding="utf-8")
        assert '"errors"' in src
        assert '"warnings"' in src
        assert '"database"' in src

    def test_startup_banner_exists(self) -> None:
        src = (ROOT / "app" / "bot.py").read_text(encoding="utf-8")
        assert "_startup_banner" in src

    def test_startup_failure_logs_traceback(self) -> None:
        src = (ROOT / "app" / "bot.py").read_text(encoding="utf-8")
        assert "traceback.format_exc()" in src

    def test_missing_token_does_not_kill_the_container(self) -> None:
        """بدون توكن تبقى العملية حية — النشر يبقى قابلا للتشخيص."""
        src = (ROOT / "app" / "bot.py").read_text(encoding="utf-8")
        assert "_idle_loop" in src
        run_body = src.split("def _run()")[1].split("def _idle_loop")[0]
        assert "raise SystemExit(1)" not in run_body


class TestEntrypointRoles:
    def test_dockerfile_runs_the_bot(self) -> None:
        """الصورة تشغّل البوت افتراضيا (الـ API له أمر خاص)."""
        for name in ("Dockerfile", "Dockerfile.prod"):
            cmd = [ln for ln in _read(name).splitlines() if ln.strip().startswith("CMD")]
            assert cmd and "python -m app.bot" in cmd[-1], f"{name} must start the bot"

    def test_api_config_uses_uvicorn(self) -> None:
        assert "uvicorn api.main:app" in _read("railway.api.json")

    def test_railway_config_has_no_start_command(self) -> None:
        """لا نحدد startCommand — يتولى Dockerfile الأمر (أقل نقاط فشل)."""
        import json

        data = json.loads(_read("railway.json"))
        assert "startCommand" not in data["deploy"]
