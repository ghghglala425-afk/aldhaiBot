# -*- coding: utf-8 -*-
"""خدمة بيئات الهدف: تشغيل/إيقاف حاوية الهدف، وعرض المهام، وتسليم إجاباتها."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.logging import get_logger
from core.models import Lab, LabInstance, Submission, User
from core.repo import add_xp
from pipeline.target_runner import is_running, start_target, stop_target

log = get_logger("core.targets")


def _norm(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


async def _instance(session: AsyncSession, user_id: int, lab_id: int) -> LabInstance | None:
    return await session.scalar(
        select(LabInstance).where(LabInstance.user_id == user_id, LabInstance.lab_id == lab_id)
    )


async def _solved_orders(session: AsyncSession, user: User, lab: Lab) -> set[int]:
    res = await session.execute(
        select(Submission).where(
            Submission.user_id == user.id, Submission.lab_id == lab.id, Submission.is_correct.is_(True)
        )
    )
    answers = {_norm(str(t.get("answer", ""))) for t in (lab.tasks or [])}
    solved: set[int] = set()
    for s in res.scalars().all():
        if _norm(s.value) in answers:
            for t in lab.tasks or []:
                if _norm(str(t.get("answer", ""))) == _norm(s.value):
                    solved.add(int(t.get("order", 0)))
    return solved


async def start(session: AsyncSession, user: User, lab: Lab) -> dict:
    if user is None:
        return {"ok": False, "error": "سجّل دخولك أولا."}
    if lab is None:
        return {"ok": False, "error": "بيئة الهدف غير متاحة."}

    # هدف خارجي (بدون Docker): يُعرض رابط جاهز
    if lab.external_url:
        inst = await _instance(session, user.id, lab.id)
        if inst is None:
            inst = LabInstance(user_id=user.id, lab_id=lab.id)
            session.add(inst)
        inst.container_id = None
        inst.url = lab.external_url
        inst.status = "external"
        inst.detail = None
        await session.commit()
        return {"ok": True, "url": lab.external_url, "status": "external", "mode": "external"}

    if not lab.docker_image:
        return {"ok": False, "error": "بيئة الهدف غير متاحة.", "mode": "guided"}

    inst = await _instance(session, user.id, lab.id)
    if inst and inst.container_id and await is_running(inst.container_id):
        return {"ok": True, "url": inst.url, "host_port": inst.host_port, "status": "running", "mode": "docker"}

    name = f"kheet_target_{lab.id}_{user.id}"
    port = int(lab.target_port or 80)
    result = await start_target(
        image=lab.docker_image,
        container_port=port,
        host_port=lab.runtime_port,
        name=name,
    )
    if inst is None:
        inst = LabInstance(user_id=user.id, lab_id=lab.id)
        session.add(inst)
    inst.container_id = result.container_id or name
    inst.url = result.url
    inst.host_port = result.host_port or None
    inst.status = "running" if result.ok else "error"
    inst.detail = result.detail or None
    await session.commit()
    if not result.ok:
        return {"ok": False, "mode": "guided", "error": result.detail or "فشل تشغيل البيئة."}
    return {"ok": True, "url": result.url, "host_port": result.host_port,
            "status": "running", "mode": "docker"}


async def stop(session: AsyncSession, user: User, lab: Lab) -> dict:
    inst = await _instance(session, user.id, lab.id) if user else None
    if not inst:
        return {"ok": True, "status": "stopped"}
    if inst.container_id:
        await stop_target(inst.container_id)
    inst.status = "stopped"
    inst.container_id = None
    inst.url = None
    await session.commit()
    return {"ok": True, "status": "stopped"}


async def status(session: AsyncSession, user: User, lab: Lab) -> dict:
    if lab.external_url:
        return {"status": "external", "url": lab.external_url, "mode": "external"}
    inst = await _instance(session, user.id, lab.id) if user else None
    if not inst or not inst.container_id:
        return {"status": "stopped", "url": None, "mode": "guided"}
    running = await is_running(inst.container_id)
    return {"status": "running" if running else "stopped",
            "url": inst.url if running else None, "mode": "docker"}


async def task_state(session: AsyncSession, user: User, lab: Lab) -> dict:
    solved = await _solved_orders(session, user, lab) if user else set()
    tasks = [
        {
            "order": int(t.get("order", i + 1)),
            "title": t.get("title", ""),
            "prompt": t.get("prompt", ""),
            "points": int(t.get("points", 0)),
            "solved": int(t.get("order", i + 1)) in solved,
        }
        for i, t in enumerate(lab.tasks or [])
    ]
    total = sum(t["points"] for t in tasks)
    earned = sum(t["points"] for t in tasks if t["solved"])
    return {"tasks": tasks, "total_points": total, "earned": earned,
            "percent": round(earned / total * 100) if total else 0}


async def submit_task(session: AsyncSession, user: User, lab: Lab, order: int, value: str) -> dict:
    if user is None:
        return {"ok": False, "error": "سجّل دخولك أولا."}
    task = next((t for t in (lab.tasks or []) if int(t.get("order", 0)) == order), None)
    if not task:
        return {"ok": False, "error": "مهمة غير موجودة."}

    solved = await _solved_orders(session, user, lab)
    if order in solved:
        return {"ok": True, "correct": True, "already": True, "xp": 0}

    correct = _norm(value) == _norm(str(task.get("answer", "")))
    session.add(Submission(user_id=user.id, lab_id=lab.id, value=value, is_correct=correct))
    await session.commit()
    if correct:
        pts = int(task.get("points", 10))
        await add_xp(session, user, pts, "lab_task", f"{lab.id}:{order}")
        return {"ok": True, "correct": True, "already": False, "xp": pts}
    return {"ok": True, "correct": False, "already": False, "xp": 0}


async def target_labs(session: AsyncSession, lesson_id: int) -> list[Lab]:
    res = await session.execute(select(Lab).where(Lab.lesson_id == lesson_id, Lab.kind == "target"))
    return list(res.scalars().all())
