# -*- coding: utf-8 -*-
"""مسارات التعلّم عبر الـAPI (تُستخدم من Mini App): تقدّم، اختبار، مختبرات، مجتمع."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import current_user
from core.db import get_session
from core.gamification import (
    add_note,
    list_bookmarks,
    list_notes,
    toggle_bookmark,
    user_rank,
    xp_leaderboard,
)
from core.learning import (
    labs_for_lesson,
    maybe_certificate,
    status_map,
    submit_flag,
    submit_quiz,
    todays_daily,
)
from core.models import Certificate, Course, Lab, Lesson, LessonAsset, Stage, User

router = APIRouter(prefix="/api", tags=["learn"])


class AttemptIn(BaseModel):
    responses: dict[str, list[int]]


class FlagIn(BaseModel):
    flag: str


class NoteIn(BaseModel):
    lesson_id: int
    text: str


@router.get("/courses/{slug}/lessons")
async def course_lessons(
    slug: str,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    course = await session.scalar(select(Course).where(Course.slug == slug))
    if not course:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "الكورس غير موجود")
    rows = await status_map(session, user, course.id)
    return [
        {
            "id": r["lesson"].id,
            "title": r["lesson"].title,
            "difficulty": r["lesson"].difficulty,
            "est_minutes": r["lesson"].est_minutes,
            "status": r["status"],
            "best_score": r["best_score"],
        }
        for r in rows
    ]


@router.get("/lessons/{lesson_id}/assets")
async def lesson_assets(lesson_id: int, session: AsyncSession = Depends(get_session)):
    res = await session.execute(
        select(LessonAsset).where(LessonAsset.lesson_id == lesson_id)
    )
    return [
        {"kind": a.kind, "lang": a.lang, "url": a.url, "duration": a.duration_sec}
        for a in res.scalars().all()
    ]


@router.post("/lessons/{lesson_id}/attempt")
async def lesson_attempt(
    lesson_id: int,
    body: AttemptIn,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    lesson = await session.get(Lesson, lesson_id)
    if not lesson:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "الدرس غير موجود")
    responses = {int(k): v for k, v in body.responses.items()}
    result = await submit_quiz(session, user, lesson, responses)
    if not result.get("ok"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, result.get("error", "خطأ"))
    if result.get("passed"):
        stage = await session.get(Stage, lesson.stage_id)
        if stage:
            await maybe_certificate(session, user, stage.course_id)
    return result


@router.get("/lessons/{lesson_id}/quiz")
async def lesson_quiz(lesson_id: int, session: AsyncSession = Depends(get_session)):
    from core.models import Option, Question, Quiz

    quiz = await session.scalar(select(Quiz).where(Quiz.lesson_id == lesson_id))
    if not quiz:
        return {"questions": []}
    qs = list(
        (await session.execute(
            select(Question).where(Question.quiz_id == quiz.id).order_by(Question.order_index)
        )).scalars().all()
    )
    out = []
    for q in qs:
        opts = list(
            (await session.execute(
                select(Option).where(Option.question_id == q.id).order_by(Option.order_index)
            )).scalars().all()
        )
        out.append(
            {
                "id": q.id,
                "text": q.text,
                "kind": q.kind,
                "options": [{"id": o.id, "text": o.text} for o in opts],
            }
        )
    return {"questions": out}


@router.get("/lessons/{lesson_id}/labs")
async def lesson_labs(lesson_id: int, session: AsyncSession = Depends(get_session)):
    labs = await labs_for_lesson(session, lesson_id)
    return [
        {"id": l.id, "title": l.title, "description": l.description, "points": l.points, "kind": l.kind}
        for l in labs
    ]


@router.post("/labs/{lab_id}/submit")
async def lab_submit(
    lab_id: int,
    body: FlagIn,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    lab = await session.get(Lab, lab_id)
    if not lab:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "المختبر غير موجود")
    return await submit_flag(session, user, lab, body.flag)


@router.get("/leaderboard")
async def leaderboard(session: AsyncSession = Depends(get_session)):
    return await xp_leaderboard(session, 20)


@router.get("/me/rank")
async def my_rank(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return {"rank": await user_rank(session, user), "xp": user.xp, "level": user.level}


@router.get("/daily")
async def daily(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    lesson = await todays_daily(session, user)
    if not lesson:
        return {"lesson": None}
    return {"lesson": {"id": lesson.id, "title": lesson.title, "summary": lesson.summary}}


@router.get("/notes")
async def notes(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = await list_notes(session, user.id)
    return [{"id": n.id, "lesson_id": n.lesson_id, "text": n.text} for n in rows]


@router.post("/notes")
async def create_note(
    body: NoteIn,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    note = await add_note(session, user.id, body.lesson_id, body.text)
    return {"id": note.id}


@router.get("/bookmarks")
async def bookmarks(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await list_bookmarks(session, user.id)


@router.post("/bookmarks/{lesson_id}")
async def bookmark(
    lesson_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    added = await toggle_bookmark(session, user.id, lesson_id)
    return {"bookmarked": added}


@router.get("/certificates")
async def certificates(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    res = await session.execute(select(Certificate).where(Certificate.user_id == user.id))
    return [
        {"code": c.code, "course_id": c.course_id, "issued_at": c.issued_at.isoformat()}
        for c in res.scalars().all()
    ]


@router.get("/certificates/verify/{code}")
async def verify_certificate(code: str, session: AsyncSession = Depends(get_session)):
    cert = await session.scalar(select(Certificate).where(Certificate.code == code))
    if not cert:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "شهادة غير موجودة")
    course = await session.get(Course, cert.course_id)
    return {"valid": True, "course": course.title if course else "", "code": cert.code}
