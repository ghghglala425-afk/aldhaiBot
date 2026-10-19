# -*- coding: utf-8 -*-
"""مُشغّل بيئات الهدف (Targets) عبر Docker.

يشغّل حاوية هدف لكل مستخدم على منفذ مضيف، ويُرجع رابطًا للوصول، ويدير إيقافها.
لا يعمل إلا إذا توفّر Docker (بيئة محلية عبر Docker Desktop).
"""
from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass

from core.logging import get_logger
from pipeline.sandbox_runner import docker_available

log = get_logger("pipeline.target_runner")


@dataclass
class TargetResult:
    ok: bool
    container_id: str = ""
    host_port: int = 0
    url: str = ""
    detail: str = ""


async def _exec(cmd: list[str], timeout: int = 90) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        with contextlib.suppress(Exception):
            proc.kill()
        return -9, "", "TIMEOUT"
    return proc.returncode or 0, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


async def _published_port(container_id: str, container_port: int) -> int:
    rc, out, _ = await _exec(["docker", "port", container_id, f"{container_port}/tcp"], timeout=20)
    if rc != 0 or not out.strip():
        return 0
    # مثال: 127.0.0.1:49153
    tail = out.strip().splitlines()[0].rsplit(":", 1)[-1]
    return int(tail) if tail.isdigit() else 0


async def start_target(
    *,
    image: str,
    container_port: int,
    host_port: int | None,
    name: str,
    timeout: int = 90,
) -> TargetResult:
    if not await docker_available():
        return TargetResult(False, detail="Docker غير متاح — شغّل Docker Desktop أولا.")

    # إن وُجدت حاوية بنفس الاسم أوقفها
    with contextlib.suppress(Exception):
        await _exec(["docker", "rm", "-f", name], timeout=30)

    publish = f"127.0.0.1:{host_port}:{container_port}" if host_port else f"{container_port}"
    cmd = [
        "docker", "run", "-d", "--rm", "--name", name,
        "--memory=512m", "--cpus=1.0", "--pids-limit=256",
        "-p", publish, image,
    ]
    rc, out, err = await _exec(cmd, timeout=timeout)
    if rc != 0:
        log.warning("فشل تشغيل الهدف %s: %s", image, err[:200])
        return TargetResult(False, detail=err[:300] or f"خروج بكود {rc}")

    cid = out.strip().splitlines()[-1][:64] if out.strip() else ""
    port = host_port or await _published_port(cid, container_port)
    url = f"http://localhost:{port}" if port else ""
    log.info("شُغّل هدف %s (حاوية %s) على %s", image, cid[:12], url)
    return TargetResult(True, container_id=cid, host_port=port or 0, url=url)


async def stop_target(container_ref: str) -> bool:
    if not container_ref:
        return False
    rc, _, _ = await _exec(["docker", "rm", "-f", container_ref], timeout=30)
    return rc == 0


async def is_running(container_ref: str) -> bool:
    if not container_ref:
        return False
    rc, out, _ = await _exec(
        ["docker", "inspect", "-f", "{{.State.Running}}", container_ref], timeout=20
    )
    return rc == 0 and out.strip() == "true"
