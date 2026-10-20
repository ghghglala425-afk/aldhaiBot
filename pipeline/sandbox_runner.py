# -*- coding: utf-8 -*-
"""مُشغّل الأكواد المعزول (Sandbox).

يحاول أولا Docker (عزل حقيقي: بلا شبكة + حدود موارد + نظام ملفات للقراءة فقط).
عند غياب Docker: لا يُنفَّذ الكود محليا إلا إذا فُعِّل SANDBOX_LOCAL صريحا؛ وإلا يُصنّف "متخطى" (تحقق نحوي فقط).
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import signal
import sys
import tempfile
from dataclasses import dataclass, field

from core.config import settings
from core.logging import get_logger
from pipeline.languages_data import LANGUAGES

log = get_logger("pipeline.sandbox")

# امتداد الملف + أمر التشغيل داخل الـSandbox
_RUN: dict[str, dict] = {
    "python": {"ext": "py", "cmd": ["python", "main.py"]},
    "javascript": {"ext": "js", "cmd": ["node", "main.js"]},
    "bash": {"ext": "sh", "cmd": ["bash", "main.sh"]},
    "php": {"ext": "php", "cmd": ["php", "main.php"]},
    "ruby": {"ext": "rb", "cmd": ["ruby", "main.rb"]},
    "c": {"ext": "c", "cmd": ["sh", "-c", "gcc main.c -o /tmp/a.out && /tmp/a.out"]},
    "cpp": {"ext": "cpp", "cmd": ["sh", "-c", "g++ main.cpp -o /tmp/a.out && /tmp/a.out"]},
}

# المفسّرات المحلية البديلة (لاستخدامها عند غياب Docker)
_LOCAL = {
    "python": [sys.executable, "main.py"],
    "javascript": ["node", "main.js"],
    "bash": ["bash", "main.sh"],
    "php": ["php", "main.php"],
    "ruby": ["ruby", "main.rb"],
}

_IMAGES = {x["slug"]: x.get("docker_image") for x in LANGUAGES}

_docker_state: bool | None = None


def _local_cmd(language: str) -> list[str] | None:
    """أمر التنفيذ المحلي إن كان المفسّر مثبّتا فعلا."""
    cmd = _LOCAL.get(language)
    if not cmd:
        return None
    exe = cmd[0]
    if os.path.basename(exe).lower().startswith("python") or exe == sys.executable:
        return cmd if os.path.exists(exe) or shutil.which(exe) else None
    return cmd if shutil.which(exe) else None


def local_languages() -> list[str]:
    return [lang for lang in _LOCAL if _local_cmd(lang)]


async def available_languages() -> list[str]:
    """اللغات القابلة للتنفيذ فعليا على هذا الخادم (Docker أو مفسّر محلي)."""
    if await docker_available():
        return list(_RUN)
    if settings.SANDBOX_LOCAL:
        return local_languages()
    return []


def _safe_env(tmp: str) -> dict[str, str]:
    """بيئة نظيفة للكود غير الموثوق: بلا أسرار أو مفاتيح الخادم."""
    return {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": tmp,
        "TMPDIR": tmp,
        "TMP": tmp,
        "TEMP": tmp,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "NO_COLOR": "1",
    }


def _limit_resources(timeout: int):
    """حدود موارد للتنفيذ المحلي (POSIX فقط)."""
    if os.name != "posix":
        return None

    def apply() -> None:  # pragma: no cover - يعتمد على النظام
        import resource

        cpu = max(1, int(timeout))
        mem = max(64, settings.SANDBOX_MEM_MB) * 1024 * 1024
        with contextlib.suppress(Exception):
            resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
        with contextlib.suppress(Exception):
            resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
        with contextlib.suppress(Exception):
            resource.setrlimit(resource.RLIMIT_FSIZE, (2 * 1024 * 1024, 2 * 1024 * 1024))
        with contextlib.suppress(Exception):
            resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))

    return apply


@dataclass
class RunResult:
    status: str  # ok | error | timeout | skipped
    engine: str = ""  # docker | local | none
    stdout: str = ""
    stderr: str = ""
    detail: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status in {"ok", "skipped"}


async def docker_available() -> bool:
    global _docker_state
    if _docker_state is not None:
        return _docker_state
    if not shutil.which("docker"):
        _docker_state = False
        return False
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "info",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=15)
        _docker_state = proc.returncode == 0
    except Exception:  # noqa: BLE001
        _docker_state = False
    log.info("Docker متاح للـSandbox: %s", _docker_state)
    return _docker_state


async def _run_cmd(
    cmd: list[str],
    cwd: str,
    timeout: int,
    *,
    env: dict[str, str] | None = None,
    isolate: bool = False,
) -> tuple[int, str, str]:
    kwargs: dict = {}
    if env is not None:
        kwargs["env"] = env
    if isolate:
        if os.name == "posix":
            kwargs["start_new_session"] = True
            preexec = _limit_resources(timeout)
            if preexec is not None:
                kwargs["preexec_fn"] = preexec
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        **kwargs,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode or 0, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")
    except asyncio.TimeoutError:
        with contextlib.suppress(Exception):
            if isolate and os.name == "posix":
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            else:
                proc.kill()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(proc.wait(), timeout=3)
        return -9, "", "TIMEOUT"


async def run_code(
    language: str, code: str, *, timeout: int | None = None, exec_enabled: bool | None = None
) -> RunResult:
    timeout = timeout or settings.SANDBOX_TIMEOUT
    do_exec = settings.VERIFY_EXEC if exec_enabled is None else exec_enabled
    runner = _RUN.get(language)
    if not runner:
        return RunResult(status="skipped", engine="none", detail=f"لا يوجد مُشغّل للغة {language}")

    tmp = tempfile.mkdtemp(prefix="sandbox_")
    try:
        path = os.path.join(tmp, f"main.{runner['ext']}")
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(code)

        if do_exec and await docker_available():
            image = _IMAGES.get(language)
            if image:
                cmd = [
                    "docker", "run", "--rm", "--network", "none",
                    f"--memory={settings.SANDBOX_MEM_MB}m",
                    f"--cpus={settings.SANDBOX_CPUS}",
                    "--pids-limit=128",
                    "--read-only", "--tmpfs", "/tmp",
                    "-v", f"{tmp}:/sandbox:ro", "-w", "/sandbox",
                    image, *runner["cmd"],
                ]
                rc, out, err = await _run_cmd(cmd, cwd=tmp, timeout=timeout)
                if rc == -9:
                    return RunResult("timeout", "docker", out, err, "انتهت المهلة")
                if rc == 0:
                    return RunResult("ok", "docker", out, err)
                return RunResult("error", "docker", out, err, f"خروج بكود {rc}")

        if do_exec and settings.SANDBOX_LOCAL:
            local = _local_cmd(language)
            if local:
                rc, out, err = await _run_cmd(
                    local, cwd=tmp, timeout=timeout, env=_safe_env(tmp), isolate=True
                )
                if rc == -9:
                    return RunResult("timeout", "local", out, err, "انتهت المهلة")
                if rc == 0:
                    return RunResult("ok", "local", out, err)
                return RunResult("error", "local", out, err, f"خروج بكود {rc}")

        if not do_exec:
            return RunResult(status="skipped", engine="none", detail="التنفيذ معطّل (VERIFY_EXEC=0)")
        if not settings.SANDBOX_LOCAL:
            return RunResult(
                status="skipped", engine="none",
                detail="لا Docker، والتنفيذ المحلي معطّل (SANDBOX_LOCAL=0) — تحقق نحوي فقط",
            )
        return RunResult(
            status="skipped", engine="none",
            detail=f"المفسّر غير مثبّت على الخادم للغة {language} — جرّب لغة أخرى",
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
