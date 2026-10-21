# -*- coding: utf-8 -*-
"""منطق التعلّم: التقدّم، الفتح المتسلسل، تصحيح الاختبارات، المختبرات، اليومي، الشهادات."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core import gamification as gami
from core.logging import get_logger
from core.models import (
    Answer,
    Attempt,
    Certificate,
    Course,
    DailyAssignment,
    Hint,
    Lab,
    Lesson,
    Option,
    Progress,
    Question,
    Quiz,
    Stage,
    Submission,
    User,
)
from core.repo import add_xp
from core.security import new_certificate_code

log = get_logger("core.learning")

STATUS_LOCKED = "locked"
STATUS_AVAILABLE = "available"
STATUS_IN_PROGRESS = "in_progress"
STATUS_PASSED = "passed"


# ---------------------------------------------------------------------
#  التقدّم والفتح المتسلسل
# ---------------------------------------------------------------------
async def ordered_lessons(session: AsyncSession, course_id: int) -> list[Lesson]:
    res = await session.execute(
        select(Lesson)
        .join(Stage, Lesson.stage_id == Stage.id)
        .where(Stage.course_id == course_id, Lesson.status.in_(["published", "outline"]))
        .order_by(Stage.order_index, Lesson.order_index)
    )
    return list(res.scalars().all())


async def get_progress(session: AsyncSession, user_id: int, lesson_id: int) -> Progress | None:
    return await session.scalar(
        select(Progress).where(Progress.user_id == user_id, Progress.lesson_id == lesson_id)
    )


async def lesson_day(session: AsyncSession, lesson: Lesson) -> int | None:
    """رقم «اليوم» لدرس = ترتيبه العالمي داخل الكورس (الدرس الأول = اليوم 1)."""
    try:
        stage = await session.get(Stage, lesson.stage_id)
        if not stage:
            return None
        lessons = await ordered_lessons(session, stage.course_id)
        ids = [x.id for x in lessons]
        if lesson.id not in ids:
            return None
        return ids.index(lesson.id) + 1
    except Exception:  # noqa: BLE001
        return None


async def next_lesson_id(session: AsyncSession, lesson: Lesson, *, only_available: bool = False) -> int | None:
    """معرّف الدرس التالي في نفس الكورس (أو None في النهاية)."""
    try:
        stage = await session.get(Stage, lesson.stage_id)
        if not stage:
            return None
        lessons = await ordered_lessons(session, stage.course_id)
        ids = [x.id for x in lessons]
        if lesson.id not in ids:
            return None
        idx = ids.index(lesson.id)
        if idx + 1 >= len(ids):
            return None
        nxt = ids[idx + 1]
        if only_available:
            row = await session.get(Lesson, nxt)
            if not row or row.status == "outline":
                return None
        return nxt
    except Exception:  # noqa: BLE001
        return None


async def _ensure(session: AsyncSession, user_id: int, lesson_id: int) -> Progress:
    p = await get_progress(session, user_id, lesson_id)
    if p is None:
        p = Progress(user_id=user_id, lesson_id=lesson_id, status=STATUS_LOCKED)
        session.add(p)
        await session.flush()
    return p


async def start_lesson(session: AsyncSession, user_id: int, lesson_id: int) -> Progress:
    """يسجّل أن المستخدم بدأ هذا الدرس.

    يُنشئ صف Progress إن لم يكن موجودا (status=in_progress) ويضبط started_at
    عند أول فتح — بلا أن يغيّر حالة الإكمال.
    """
    prog = await _ensure(session, user_id, lesson_id)
    now = dt.datetime.now(dt.timezone.utc)
    changed = False
    if prog.started_at is None:
        prog.started_at = now
        changed = True
    if prog.status == STATUS_LOCKED:
        prog.status = STATUS_IN_PROGRESS
        changed = True
    if changed:
        prog.updated_at = now
        await session.commit()
        await session.refresh(prog)
    return prog


async def finish_lesson_time(session: AsyncSession, user_id: int, lesson_id: int) -> None:
    """يسجّل المدة التي قضاها المستخدم في الدرس."""
    prog = await get_progress(session, user_id, lesson_id)
    if not prog or not prog.started_at:
        return
    started = prog.started_at
    now = dt.datetime.now(dt.timezone.utc)
    # SQLite يخلّي الحقول بلا منطقة زمنية — نوحّدها قبل الطرح
    if started.tzinfo is None:
        started = started.replace(tzinfo=dt.timezone.utc)
    elapsed = (now - started).total_seconds()
    if elapsed < 5:  # نقرة عابرة
        return
    from core.features import track_lesson_time

    await track_lesson_time(session, user_id, lesson_id, int(elapsed))


async def status_map(session: AsyncSession, user: User, course_id: int) -> list[dict]:
    """يُرجع قائمة الدروس مع حالتها للمستخدم (مع الفتح المتسلسل)."""
    lessons = await ordered_lessons(session, course_id)
    res = await session.execute(
        select(Progress).where(Progress.user_id == user.id)
    )
    by_lesson = {p.lesson_id: p for p in res.scalars().all()}
    passed = {lid: p for lid, p in by_lesson.items() if p.status == STATUS_PASSED}
    in_progress = {lid for lid, p in by_lesson.items() if p.status == STATUS_IN_PROGRESS}

    out: list[dict] = []
    prev_passed = True
    for lsn in lessons:
        if lsn.id in passed:
            status = STATUS_PASSED
            prev_passed = True
        elif prev_passed:
            # الدرس التالي يبقى مقفلا حتى اجتياز هذا (بدأ أو لا)
            status = STATUS_IN_PROGRESS if lsn.id in in_progress else STATUS_AVAILABLE
            prev_passed = False
        else:
            status = STATUS_LOCKED
        out.append({
            "lesson": lsn,
            "status": status,
            "best_score": passed[lsn.id].best_score if lsn.id in passed else 0,
            "started_at": by_lesson[lsn.id].started_at if lsn.id in by_lesson else None,
        })
    return out


async def is_unlocked(session: AsyncSession, user: User, lesson: Lesson) -> bool:
    stage = await session.get(Stage, lesson.stage_id)
    if not stage:
        return False
    lessons = await ordered_lessons(session, stage.course_id)
    prior_ids: list[int] = []
    for lsn in lessons:
        if lsn.id == lesson.id:
            break
        prior_ids.append(lsn.id)
    else:
        return False
    if not prior_ids:
        return True
    passed = await session.scalar(
        select(func.count())
        .select_from(Progress)
        .where(
            Progress.user_id == user.id,
            Progress.lesson_id.in_(prior_ids),
            Progress.status == STATUS_PASSED,
        )
    )
    return int(passed or 0) == len(prior_ids)


# ---------------------------------------------------------------------
#  تصحيح الاختبار
# ---------------------------------------------------------------------
async def submit_quiz(
    session: AsyncSession, user: User, lesson: Lesson, responses: dict[int, list[int]]
) -> dict:
    """responses: {question_id: [option_id, ...]} — يُرجع نتيجة كاملة."""
    quiz = await session.scalar(select(Quiz).where(Quiz.lesson_id == lesson.id))
    if not quiz:
        return {"ok": False, "error": "لا يوجد اختبار لهذا الدرس."}

    if not await is_unlocked(session, user, lesson):
        return {"ok": False, "error": "الدرس مقفل."}

    prog = await _ensure(session, user.id, lesson.id)
    if lesson.max_attempts and prog.attempts_count >= lesson.max_attempts:
        return {"ok": False, "error": "استنفدت عدد المحاولات المسموح."}

    was_passed = prog.status == STATUS_PASSED

    res = await session.execute(
        select(Question).where(Question.quiz_id == quiz.id).order_by(Question.order_index)
    )
    questions = list(res.scalars().all())

    attempt = Attempt(user_id=user.id, quiz_id=quiz.id, lesson_id=lesson.id)
    session.add(attempt)
    await session.flush()

    earned = 0
    total = 0
    detail: list[dict] = []
    for q in questions:
        qopts = await session.execute(select(Option).where(Option.question_id == q.id))
        opts = list(qopts.scalars().all())
        correct = {o.id for o in opts if o.is_correct}
        chosen = set(responses.get(q.id, []))
        total += q.points
        is_ok = chosen == correct
        if is_ok:
            earned += q.points
        session.add(
            Answer(attempt_id=attempt.id, question_id=q.id, response=",".join(map(str, chosen)),
                   is_correct=is_ok, points=q.points if is_ok else 0)
        )
        detail.append({"question_id": q.id, "correct": is_ok,
                       "explanation": q.explanation, "correct_ids": sorted(correct)})

    score = round(earned / total * 100) if total else 0
    passed = score >= (lesson.min_score or 70)
    attempt.score = score
    attempt.passed = passed
    attempt.finished_at = dt.datetime.now(dt.timezone.utc)

    prog.attempts_count = (prog.attempts_count or 0) + 1
    prog.best_score = max(prog.best_score or 0, score)
    if passed:
        prog.status = STATUS_PASSED
    elif not was_passed:
        # إعادة اختبار درس مجتاز لا تُسقط إنجازه.
        prog.status = STATUS_IN_PROGRESS
    if prog.started_at is None:
        prog.started_at = dt.datetime.now(dt.timezone.utc)
    if passed and not prog.completed_at:
        prog.completed_at = dt.datetime.now(dt.timezone.utc)

    new_badges: list[str] = []
    first_pass = passed and not was_passed
    if first_pass:
        await add_xp(session, user, lesson.xp_reward or 50, "lesson_pass", str(lesson.id))
        await gami.update_streak(session, user)
        new_badges = await gami.evaluate_badges(session, user)
    await session.commit()

    # تسجيل مدة التعلّم (من أول فتح الدرس حتى إنهاء الاختبار)
    try:
        await finish_lesson_time(session, user.id, lesson.id)
    except Exception as e:  # noqa: BLE001
        log.debug("تعذّر تسجيل مدة التعلّم: %s", e)

    return {
        "ok": True, "score": score, "passed": passed, "detail": detail,
        "xp": lesson.xp_reward if first_pass else 0, "badges": new_badges,
        "first_pass": first_pass,
    }


# ---------------------------------------------------------------------
#  المختبرات (CTF)
# ---------------------------------------------------------------------
async def labs_for_lesson(session: AsyncSession, lesson_id: int) -> list[Lab]:
    res = await session.execute(select(Lab).where(Lab.lesson_id == lesson_id))
    return list(res.scalars().all())


async def submit_flag(session: AsyncSession, user: User, lab: Lab, value: str) -> dict:
    if user is None:
        return {"ok": False, "correct": False, "error": "سجّل دخولك أولا."}
    if lab is None:
        return {"ok": False, "correct": False, "error": "المختبر غير موجود."}
    correct = value.strip() in {str(f).strip() for f in (lab.flags or [])}
    session.add(Submission(user_id=user.id, lab_id=lab.id, value=value, is_correct=correct))
    await session.commit()
    if correct:
        already = await session.scalar(
            select(func.count()).select_from(Submission).where(
                Submission.user_id == user.id, Submission.lab_id == lab.id, Submission.is_correct.is_(True)
            )
        )
        # لا نضاعف النقاط إن كان قد حلّه سابقا (عدا هذه المحاولة)
        if (already or 0) <= 1:
            await add_xp(session, user, lab.points or 100, "lab_solve", str(lab.id))
            await gami.evaluate_badges(session, user)
    return {"ok": True, "correct": correct}


async def reveal_hint(session: AsyncSession, user: User, lab: Lab, index: int) -> dict:
    if user is None:
        return {"ok": False, "error": "سجّل دخولك أولا."}
    if lab is None:
        return {"ok": False, "error": "المختبر غير موجود."}
    cost = 0
    res = await session.execute(
        select(Hint).where(Hint.lab_id == lab.id).order_by(Hint.order_index)
    )
    hints = list(res.scalars().all())
    if index < 0 or index >= len(hints):
        return {"ok": False, "error": "لا يوجد تلميح بهذا الرقم."}
    hint = hints[index]
    cost = hint.cost_xp or 0
    if cost and (user.xp or 0) < cost:
        return {"ok": False, "error": f"تحتاج {cost} نقطة لكشف التلميح."}
    if cost:
        user.xp -= cost
        await session.commit()
    return {"ok": True, "hint": hint.text, "cost": cost}


# ---------------------------------------------------------------------
#  الدرس اليومي
# ---------------------------------------------------------------------
async def todays_daily(session: AsyncSession, user: User, course_id: int | None = None) -> Lesson | None:
    today = dt.date.today()
    existing = await session.scalar(
        select(DailyAssignment).where(DailyAssignment.user_id == user.id, DailyAssignment.date == today)
    )
    if existing:
        return await session.get(Lesson, existing.lesson_id)

    # اختر أول درس متاح غير مُكتمل
    stmt = select(Course).where(Course.is_published.is_(True)).order_by(Course.order_index)
    courses = list((await session.execute(stmt)).scalars().all())
    for course in courses:
        if course_id and course.id != course_id:
            continue
        for row in await status_map(session, user, course.id):
            if row["status"] == STATUS_AVAILABLE:
                lesson = row["lesson"]
                session.add(DailyAssignment(user_id=user.id, lesson_id=lesson.id, date=today))
                await session.commit()
                return lesson
    return None


# ---------------------------------------------------------------------
#  الشهادات
# ---------------------------------------------------------------------
async def maybe_certificate(session: AsyncSession, user: User, course_id: int) -> Certificate | None:
    lessons = await ordered_lessons(session, course_id)
    if not lessons:
        return None
    ids = [l.id for l in lessons]
    passed = await session.scalar(
        select(func.count()).select_from(Progress).where(
            Progress.user_id == user.id, Progress.lesson_id.in_(ids), Progress.status == STATUS_PASSED
        )
    )
    if (passed or 0) < len(ids):
        return None
    existing = await session.scalar(
        select(Certificate).where(Certificate.user_id == user.id, Certificate.course_id == course_id)
    )
    if existing:
        return existing
    cert = Certificate(user_id=user.id, course_id=course_id, code=new_certificate_code())
    session.add(cert)
    await session.commit()
    await session.refresh(cert)
    return cert


async def course_progress_summary(session: AsyncSession, user: User, course_id: int) -> dict:
    rows = await status_map(session, user, course_id)
    done = sum(1 for r in rows if r["status"] == STATUS_PASSED)
    return {"total": len(rows), "passed": done, "percent": round(done / len(rows) * 100) if rows else 0}
