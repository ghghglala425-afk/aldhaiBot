# -*- coding: utf-8 -*-
"""مُشغّل الأكواد المعزول (Sandbox).

سياسة الأمان: **لا يُنفَّذ أي كود على مضيف الخادم إطلاقا.**
مسارَان فقط:
  1) خدمة تنفيذ خارجية معزولة (Judge0 CE أو Piston) عند ضبط `EXEC_API_URL`.
  2) Docker محلي/على الخادم (بلا شبكة + حدود موارد + قراءة فقط).
إن غاب الاثنان تُعاد النتيجة "skipped" ولا يُشغَّل أي كود.
"""
from __future__ import annotations

import asyncio
import base64
import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field

import httpx

from core.config import settings
from core.logging import get_logger
from pipeline.languages_data import LANGUAGES

log = get_logger("pipeline.sandbox")

# امتداد الملف + أمر التشغيل داخل Docker
_RUN: dict[str, dict] = {
    "python": {"ext": "py", "cmd": ["python", "main.py"]},
    "javascript": {"ext": "js", "cmd": ["node", "main.js"]},
    "bash": {"ext": "sh", "cmd": ["bash", "main.sh"]},
    "php": {"ext": "php", "cmd": ["php", "main.php"]},
    "ruby": {"ext": "rb", "cmd": ["ruby", "main.rb"]},
    "c": {"ext": "c", "cmd": ["sh", "-c", "gcc main.c -o /tmp/a.out && /tmp/a.out"]},
    "cpp": {"ext": "cpp", "cmd": ["sh", "-c", "g++ main.cpp -o /tmp/a.out && /tmp/a.out"]},
}

# أسماء Piston القياسية عند اختلافها عن مفاتيحنا
_PISTON_NAMES = {"cpp": "c++"}

# معرّفات اللغات في Judge0 CE
_JUDGE0_IDS = {
    "python": 71,
    "javascript": 63,
    "bash": 46,
    "php": 68,
    "ruby": 72,
    "c": 50,
    "cpp": 54,
}

_IMAGES = {x["slug"]: x.get("docker_image") for x in LANGUAGES}

_docker_state: bool | None = None
_remote_versions: dict[str, str] | None = None
_judge0_state: bool | None = None
_remote_fail_until: float = 0.0

MAX_STDOUT = 20_000
MAX_STDERR = 10_000


def _remote_base() -> str:
    return (settings.EXEC_API_URL or "").strip().rstrip("/")


def _provider() -> str:
    name = (settings.EXEC_PROVIDER or "").strip().lower()
    if name in {"piston", "judge0"}:
        return name
    return "judge0" if "judge0" in _remote_base().lower() else "piston"


def provider_name() -> str:
    return "Judge0" if _provider() == "judge0" else "Piston"


def _remote_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if settings.EXEC_API_KEY:
        headers["Authorization"] = f"Bearer {settings.EXEC_API_KEY}"
    return headers


def _judge0_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if settings.EXEC_API_KEY:
        headers["X-Auth-Token"] = settings.EXEC_API_KEY
    return headers


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _unb64(value) -> str:
    if not value:
        return ""
    try:
        return base64.b64decode(str(value), validate=True).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return str(value)


async def _piston_versions() -> dict[str, str]:
    """يجلب خريطة (اسم اللغة/الاسم البديل -> الإصدار) من خدمة Piston."""
    global _remote_versions, _remote_fail_until
    if _remote_versions is not None:
        return _remote_versions
    base = _remote_base()
    if not base or time.monotonic() < _remote_fail_until:
        return {}
    try:
        async with httpx.AsyncClient(timeout=min(10, settings.EXEC_API_TIMEOUT)) as client:
            resp = await client.get(f"{base}/runtimes", headers=_remote_headers())
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:  # noqa: BLE001
        _remote_fail_until = time.monotonic() + 120
        log.warning("تعذّر جلب لغات خدمة التنفيذ الخارجية: %s", e)
        return {}
    mapping: dict[str, str] = {}
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            version = str(item.get("version") or "")
            names = [item.get("language"), *(item.get("aliases") or [])]
            for name in names:
                if name and name not in mapping:
                    mapping[str(name)] = version
    _remote_versions = mapping
    return mapping


async def _judge0_available() -> bool:
    global _judge0_state, _remote_fail_until
    if _judge0_state is not None:
        return _judge0_state
    base = _remote_base()
    if not base or time.monotonic() < _remote_fail_until:
        return False
    try:
        async with httpx.AsyncClient(timeout=min(10, settings.EXEC_API_TIMEOUT)) as client:
            resp = await client.get(f"{base}/languages", headers=_remote_headers())
            resp.raise_for_status()
    except Exception as e:  # noqa: BLE001
        _judge0_state = False
        _remote_fail_until = time.monotonic() + 120
        log.warning("تعذّر الوصول لخدمة Judge0 الخارجية: %s", e)
        return False
    _judge0_state = True
    return True


async def remote_available() -> bool:
    if not _remote_base():
        return False
    if _provider() == "judge0":
        return await _judge0_available()
    return bool(await _piston_versions())


async def available_languages() -> list[str]:
    """اللغات القابلة للتنفيذ فعليا (خدمة خارجية أو Docker) — بلا أي تنفيذ محلي."""
    if await remote_available():
        if _provider() == "judge0":
            return [lang for lang in _RUN if lang in _JUDGE0_IDS]
        versions = await _piston_versions()
        langs = [
            lang for lang in _RUN
            if versions.get(_PISTON_NAMES.get(lang, lang)) or versions.get(lang)
        ]
        if langs:
            return langs
    if await docker_available():
        return list(_RUN)
    return []


@dataclass
class RunResult:
    status: str  # ok | error | timeout | skipped
    engine: str = ""  # piston | docker | none
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


async def _run_cmd(cmd: list[str], cwd: str, timeout: int) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode or 0, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=3)
        except Exception:  # noqa: BLE001
            pass
        return -9, "", "TIMEOUT"


async def _run_remote(language: str, code: str, timeout: int) -> RunResult:
    """ينفّذ الكود في خدمة Piston خارجية (لا شيء يُنفَّذ على مضيف الخادم)."""
    base = _remote_base()
    if not base:
        return RunResult("skipped", "none", detail="خدمة التنفيذ الخارجية غير مضبوطة")
    names = await _piston_versions()
    piston_lang = _PISTON_NAMES.get(language, language)
    version = names.get(piston_lang) or names.get(language)
    if not version:
        return RunResult(
            "skipped", "none",
            detail=f"اللغة {language} غير متاحة في خدمة التنفيذ الخارجية",
        )
    payload = {
        "language": piston_lang,
        "version": version,
        "files": [
            {"name": f"main.{_RUN[language]['ext']}", "content": code},
        ],
        "stdin": "",
        "args": [],
        "compile_timeout": min(timeout * 1000, 10_000),
        "run_timeout": min(timeout * 1000, 3_000),
    }
    try:
        async with httpx.AsyncClient(timeout=settings.EXEC_API_TIMEOUT) as client:
            resp = await client.post(
                f"{base}/execute", json=payload, headers=_remote_headers()
            )
    except Exception as e:  # noqa: BLE001
        return RunResult("skipped", "none", detail=f"تعذّر الوصول لخدمة التنفيذ الخارجية: {e}")

    if resp.status_code == 429:
        return RunResult(
            "skipped", "none",
            detail="خدمة التنفيذ الخارجية مشغولة الآن (429) — أعد المحاولة بعد لحظات",
        )
    if resp.status_code >= 400:
        return RunResult(
            "skipped", "none",
            detail=f"خدمة التنفيذ الخارجية رفضت الطلب ({resp.status_code})",
        )
    try:
        data = resp.json()
    except Exception:  # noqa: BLE001
        return RunResult("error", "piston", detail="رد غير صالح من خدمة التنفيذ الخارجية")

    run = data.get("run") or {}
    comp = data.get("compile") or {}
    out = str(run.get("stdout") or "")[:MAX_STDOUT]
    err = str(run.get("stderr") or "")
    compile_err = str(comp.get("stderr") or "")
    if compile_err:
        err = (compile_err + "\n" + err).strip()
    err = err[:MAX_STDERR]
    rc = run.get("code")
    signal = run.get("signal")
    if signal:
        if "KILL" in str(signal).upper() or "TERM" in str(signal).upper():
            return RunResult("timeout", "piston", out, err, "انتهت المهلة في خدمة التنفيذ")
        return RunResult("error", "piston", out, err, f"أُنهي بإشارة {signal}")
    if rc == 0:
        return RunResult("ok", "piston", out, err)
    return RunResult("error", "piston", out, err, f"خروج بكود {rc}")


async def _run_judge0(language: str, code: str, timeout: int) -> RunResult:
    """ينفّذ الكود في Judge0 CE خارجي (لا شيء يُنفَّذ على مضيف الخادم)."""
    base = _remote_base()
    lang_id = _JUDGE0_IDS.get(language)
    if not base or not lang_id:
        return RunResult("skipped", "none", detail=f"اللغة {language} غير متاحة في Judge0")

    payload = {
        "source_code": _b64(code),
        "language_id": lang_id,
        "stdin": "",
        "cpu_time_limit": max(1, min(timeout, 5)),
        "wall_time_limit": max(2, min(timeout + 2, 10)),
        "memory_limit": max(64, settings.SANDBOX_MEM_MB) * 1024,
    }
    try:
        async with httpx.AsyncClient(timeout=settings.EXEC_API_TIMEOUT) as client:
            resp = await client.post(
                f"{base}/submissions?base64_encoded=true&wait=true",
                json=payload, headers=_judge0_headers(),
            )
    except Exception as e:  # noqa: BLE001
        return RunResult("skipped", "none", detail=f"تعذّر الوصول لخدمة Judge0 الخارجية: {e}")

    if resp.status_code == 429:
        return RunResult(
            "skipped", "none",
            detail="خدمة التنفيذ الخارجية مشغولة الآن (429) — أعد المحاولة بعد لحظات",
        )
    if resp.status_code >= 400:
        return RunResult(
            "skipped", "none",
            detail=f"خدمة التنفيذ الخارجية رفضت الطلب ({resp.status_code})",
        )
    try:
        data = resp.json()
    except Exception:  # noqa: BLE001
        return RunResult("error", "judge0", detail="رد غير صالح من خدمة Judge0")

    status = data.get("status") or {}
    sid = status.get("id")
    out = _unb64(data.get("stdout"))[:MAX_STDOUT]
    err = _unb64(data.get("stderr"))
    comp = _unb64(data.get("compile_output")) or _unb64(data.get("message"))
    if comp:
        err = (comp + "\n" + err).strip()
    err = err[:MAX_STDERR]

    if sid == 3:
        return RunResult("ok", "judge0", out, err)
    if sid == 5:
        return RunResult("timeout", "judge0", out, err, "انتهت المهلة في خدمة Judge0")
    return RunResult(
        "error", "judge0", out, err,
        f"Judge0: {status.get('description') or 'فشل التنفيذ'}",
    )


async def run_code(
    language: str, code: str, *, timeout: int | None = None, exec_enabled: bool | None = None
) -> RunResult:
    timeout = timeout or settings.SANDBOX_TIMEOUT
    do_exec = settings.VERIFY_EXEC if exec_enabled is None else exec_enabled
    runner = _RUN.get(language)
    if not runner:
        return RunResult(status="skipped", engine="none", detail=f"لا يوجد مُشغّل للغة {language}")

    # الخدمة الخارجية أولا: لا شيء يعمل على مضيف هذا الجهاز/الخادم.
    if do_exec and await remote_available():
        if _provider() == "judge0":
            return await _run_judge0(language, code, timeout)
        return await _run_remote(language, code, timeout)

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

        if not do_exec:
            return RunResult(status="skipped", engine="none", detail="التنفيذ معطّل (VERIFY_EXEC=0)")
        return RunResult(
            status="skipped", engine="none",
            detail=(
                "لا Docker ولا خدمة تنفيذ خارجية — التنفيذ على مضيف الخادم معطّل نهائيا، "
                "ولم يُشغَّل أي كود."
            ),
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
