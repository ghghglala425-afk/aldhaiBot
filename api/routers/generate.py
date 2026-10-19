# -*- coding: utf-8 -*-
"""مسارات لوحة الإدارة: تشغيل التوليد ومتابعته."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel

from api.deps import current_admin
from core.config import settings
from core.logging import get_logger
from core.models import User
from pipeline.build_all import build
from pipeline.taxonomy import iter_lessons

router = APIRouter(prefix="/api/admin", tags=["admin"])
log = get_logger("api.generate")

_jobs: dict[str, dict] = {}


class GenerateIn(BaseModel):
    courses: list[str] | None = None
    limit: int = 0
    publish: bool = False
    only_missing: bool = False


async def _run_job(job_id: str, body: GenerateIn) -> None:
    _jobs[job_id] = {"status": "running", "stats": None}
    plans = iter_lessons(body.courses)
    if body.limit:
        plans = plans[: body.limit]
    try:
        stats = await build(
            plans,
            publish=body.publish or settings.AUTO_PUBLISH,
            only_missing=body.only_missing,
            check_exec=settings.VERIFY_EXEC,
        )
        _jobs[job_id] = {"status": "done", "stats": stats, "total": len(plans)}
    except Exception as e:  # noqa: BLE001
        log.exception("فشل مهمة التوليد %s", job_id)
        _jobs[job_id] = {"status": "error", "error": str(e)}


@router.post("/generate")
async def start_generate(
    body: GenerateIn,
    tasks: BackgroundTasks,
    _admin: User = Depends(current_admin),
):
    if not settings.ai_configured:
        return {"ok": False, "error": "AI_API_KEY غير مضبوط"}
    job_id = f"job-{len(_jobs) + 1}"
    tasks.add_task(_run_job, job_id, body)
    return {"ok": True, "job_id": job_id, "queued_lessons": len(iter_lessons(body.courses)[: body.limit or None])}


@router.get("/generate/{job_id}")
async def generate_status(job_id: str, _admin: User = Depends(current_admin)):
    return _jobs.get(job_id, {"status": "unknown"})
