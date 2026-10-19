# -*- coding: utf-8 -*-
"""ميزات تعلّم متقدمة: مراجعة متباعدة، بطاقات، تفسير مفصّل، تحديات، إنجازات.

تُستدعى من المعالجات (app/handlers) وتستعمل الجداول الموجودة في core/models.py.
"""
from __future__ import annotations

import datetime as dt
import random
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.logging import get_logger
from core.models import (
    CodeSample,
    Course,
    Lesson,
    Option,
    Progress,
    Question,
    Quiz,
    User,
)

log = get_logger("core.learn_features")


# =============================================================================
#  1. المراجعة المتباعدة (Spaced Repetition) — محسّنة
# =============================================================================
async def schedule_review(
    session: AsyncSession, user_id: int, lesson_id: int, quality: int
) -> dict:
    """جدولة المراجعة بخوارزمية SM-2.

    quality: 0-5 (0 = نسيان تام، 5 = استرجاع مثالي).
    """
    from core.models import ReviewSchedule

    review = await session.scalar(
        select(ReviewSchedule).where(
            ReviewSchedule.user_id == user_id,
            ReviewSchedule.lesson_id == lesson_id,
        )
    )
    if not review:
        review = ReviewSchedule(
            user_id=user_id,
            lesson_id=lesson_id,
            next_review=dt.date.today(),
            ease_factor=2.5,
            interval=1,
            repetition=0,
            last_quality=0,
        )
        session.add(review)
        await session.flush()

    if quality >= 3:
        review.ease_factor = max(
            1.3, review.ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
        )
        if review.repetition == 0:
            review.interval = 1
        elif review.repetition == 1:
            review.interval = 3
        elif review.repetition == 2:
            review.interval = 7
        else:
            review.interval = int(round(review.interval * review.ease_factor))
        review.repetition += 1
    else:
        review.repetition = 0
        review.interval = 1
        review.ease_factor = max(1.3, review.ease_factor - 0.2)

    review.next_review = dt.date.today() + dt.timedelta(days=review.interval)
    review.last_quality = quality
    await session.commit()
    await session.refresh(review)
    return {
        "ok": True,
        "interval": review.interval,
        "next_review": review.next_review.isoformat(),
        "ease": round(review.ease_factor, 2),
    }


async def due_reviews(session: AsyncSession, user_id: int, limit: int = 5) -> list[dict]:
    """الدروس المستحقة للمراجعة اليوم."""
    from core.models import ReviewSchedule

    rows = list(
        (
            await session.execute(
                select(ReviewSchedule, Lesson)
                .join(Lesson, ReviewSchedule.lesson_id == Lesson.id)
                .where(ReviewSchedule.user_id == user_id)
                .where(ReviewSchedule.next_review <= dt.date.today())
                .order_by(ReviewSchedule.next_review)
                .limit(limit)
            )
        ).all()
    )
    return [
        {"lesson": lesson, "schedule": sched, "overdue": (dt.date.today() - sched.next_review).days}
        for sched, lesson in rows
    ]


# =============================================================================
#  2. بطاقات المراجعة السريعة (Flashcards)
# =============================================================================
async def build_flashcards(session: AsyncSession, lesson_id: int, limit: int = 10) -> list[dict]:
    """يبني بطاقات مراجعة من أسئلة الاختبار (وجه/ظهر)."""
    quiz = await session.scalar(select(Quiz).where(Quiz.lesson_id == lesson_id))
    if not quiz:
        return []
    questions = list(
        (
            await session.execute(
                select(Question).where(Question.quiz_id == quiz.id).order_by(Question.order_index)
            )
        ).scalars().all()
    )
    cards: list[dict] = []
    for q in questions[:limit]:
        opts = list(
            (
                await session.execute(
                    select(Option).where(Option.question_id == q.id).order_by(Option.order_index)
                )
            ).scalars().all()
        )
        correct = [o.text for o in opts if o.is_correct]
        cards.append({
            "question_id": q.id,
            "front": q.text,
            "back": correct[0] if correct else "",
            "options": [o.text for o in opts],
            "explanation": q.explanation or "",
        })
    return cards


def render_flashcard(card: dict, index: int, total: int, revealed: bool = False) -> str:
    """يعرض بطاقة مراجعة (أمام/ظهر) — المنسّق في app.lesson_view."""
    from app.lesson_view import render_flashcard as _render

    return _render(card, index, total, revealed)


# =============================================================================
#  3. الشرح المفصّل (Deep Dive) — بمستويات
# =============================================================================
async def deep_dive(session: AsyncSession, lesson_id: int, level: str = "standard") -> dict:
    """ملخّص الدرس بمستويات عمق مختلفة."""
    lesson = await session.get(Lesson, lesson_id)
    if not lesson:
        return {"ok": False, "error": "الدرس غير موجود."}

    codes = list(
        (
            await session.execute(
                select(CodeSample).where(CodeSample.lesson_id == lesson_id).order_by(CodeSample.order_index)
            )
        ).scalars().all()
    )

    if level == "quick":
        body = "\n".join(f"  ▫️ {p}" for p in (lesson.key_points or [])[:5])
        return {
            "ok": True,
            "title": "⚡ ملخّص سريع",
            "body": body or (lesson.summary or ""),
        }

    if level == "deep":
        parts = [f"📖 <b>{lesson.title}</b>", "", lesson.summary or ""]
        if lesson.content_md:
            parts.append("")
            parts.append(lesson.content_md[:2500])
        for c in codes[:6]:
            parts.append("")
            parts.append(f"💻 <b>{c.title}</b>")
            parts.append(f"<pre>{c.code}</pre>")
            if c.explanation:
                parts.append(f"💬 <i>{c.explanation}</i>")
        return {"ok": True, "title": "🔬 غوص عميق", "body": "\n".join(parts)}

    # standard
    parts = [f"📖 <b>{lesson.title}</b>", "", lesson.summary or ""]
    if lesson.objectives:
        parts.append("")
        parts.append("🎯 <b>الأهداف:</b>")
        parts.extend(f"  {i}️⃣ {o}" for i, o in enumerate(lesson.objectives, 1))
    if lesson.key_points:
        parts.append("")
        parts.append("🔑 <b>نقاط المفتاح:</b>")
        parts.extend(f"  🟢 {p}" for p in lesson.key_points)
    if lesson.memory_hook:
        parts.append("")
        parts.append(f"🧠 <i>{lesson.memory_hook}</i>")
    return {"ok": True, "title": "📘 الشرح", "body": "\n".join(parts)}


# =============================================================================
#  4. نقاط القوة والضعف (Strengths / Weaknesses)
# =============================================================================
async def skill_breakdown(session: AsyncSession, user_id: int) -> dict:
    """يحلّل نقاط القوة والضعف من نتائج الاختبارات."""
    from core.models import Answer, Attempt

    attempts = list(
        (
            await session.execute(
                select(Attempt).where(Attempt.user_id == user_id, Attempt.passed.is_(True))
            )
        ).scalars().all()
    )
    if not attempts:
        return {"ok": False, "error": "لا توجد اختبارات مكتملة بعد."}

    best: dict[int, int] = {}
    for a in attempts:
        best[a.lesson_id] = max(best.get(a.lesson_id, 0), a.score)

    scores = list(best.values())
    avg = sum(scores) / len(scores)
    strong = [lid for lid, sc in best.items() if sc >= 85]
    weak = [lid for lid, sc in best.items() if sc < 60]

    weak_lessons = []
    for lid in weak[:5]:
        lesson = await session.get(Lesson, lid)
        if lesson:
            weak_lessons.append({"id": lid, "title": lesson.title, "score": best[lid]})

    return {
        "ok": True,
        "average": round(avg),
        "strong_count": len(strong),
        "weak_count": len(weak),
        "weak_lessons": weak_lessons,
        "total": len(best),
    }


# =============================================================================
#  5. خطة التعلّم الأسبوعية (Weekly Study Plan)
# =============================================================================
async def weekly_plan(session: AsyncSession, user_id: int, days: int = 7) -> list[dict]:
    """خطة أسبوعية: كم درسا في اليوم."""
    from core.learning import ordered_lessons, status_map

    courses = list(
        (
            await session.execute(
                select(Course).where(Course.is_published.is_(True)).order_by(Course.order_index)
            )
        ).scalars().all()
    )
    pending: list[Lesson] = []
    for course in courses:
        user = await session.get(User, user_id)
        if not user:
            break
        rows = await status_map(session, user, course.id)
        for r in rows:
            if r["status"] != "passed":
                pending.append(r["lesson"])
        if len(pending) >= days * 2:
            break

    plan = []
    for i in range(days):
        chunk = pending[i * 2:(i + 1) * 2]
        plan.append({
            "day": i + 1,
            "lessons": [{"id": l.id, "title": l.title, "minutes": l.est_minutes or 20} for l in chunk],
        })
    return plan


# =============================================================================
#  6. إنجازات إضافية (Extra Achievements)
# =============================================================================
EXTRA_BADGES = [
    ("perfect_score", "🎯", "جولة كاملة بلا خطأ", "perfect_lesson"),
    ("speed_runner", "⚡", "أسرع 10 دروس", "fast_lesson"),
    ("night_owl", "🦉", "دراسة بعد منتصف الليل", "night_lesson"),
    ("early_bird", "🌅", "دراسة قبل الساعة 7", "morning_lesson"),
    ("reviewer", "🔁", "راجع 20 درسا", "review_lesson"),
    ("collector", "🗂️", "أتمم 5 لغات", "finish_languages"),
    ("streak_7", "🔥", "سلسلة 7 أيام", "streak_7"),
    ("streak_30", "🏆", "سلسلة 30 يوما", "streak_30"),
    ("quiz_master", "🎓", "100 اختبار ناجح", "quiz_100"),
    ("code_reader", "👁️", "قرأ 50 كودا", "read_50_codes"),
]


async def evaluate_extra_badges(session: AsyncSession, user_id: int) -> list[str]:
    """يقيّم الشارات الإضافية ويرجع أسماء الجديدة."""
    from core.gamification import evaluate_badges
    from core.models import Badge, UserBadge

    user = await session.get(User, user_id)
    if not user:
        return []

    passed = await session.scalar(
        select(func.count()).select_from(Progress).where(
            Progress.user_id == user_id, Progress.status == "passed"
        )
    ) or 0
    attempts = await session.scalar(
        select(func.count()).select_from(Attempt).where(Attempt.user_id == user_id)
    ) or 0
    perfect = await session.scalar(
        select(func.count()).select_from(Attempt).where(
            Attempt.user_id == user_id, Attempt.score == 100
        )
    ) or 0

    earned: list[str] = []
    checks = {
        "perfect_lesson": perfect >= 1,
        "streak_7": (user.streak_count or 0) >= 7,
        "streak_30": (user.streak_count or 0) >= 30,
        "quiz_100": attempts >= 100,
    }
    for slug, _icon, _desc, key in EXTRA_BADGES:
        if key not in checks or not checks[key]:
            continue
        badge = await session.scalar(select(Badge).where(Badge.slug == slug))
        if not badge:
            continue
        exists = await session.scalar(
            select(UserBadge).where(
                UserBadge.user_id == user_id, UserBadge.badge_id == badge.id
            )
        )
        if exists:
            continue
        session.add(UserBadge(user_id=user_id, badge_id=badge.id))
        earned.append(badge.title)

    if earned:
        await session.commit()
    return earned


# =============================================================================
#  7. تحدّي اليوم (Daily Challenge)
# =============================================================================
async def daily_challenge(session: AsyncSession, user_id: int) -> dict:
    """يولّد تحديا يوميا (سؤال سريع من دروس مختلف��)."""
    from core.models import Attempt

    # درس عشوائي نجح فيه المستخدم
    passed_ids = list(
        (
            await session.execute(
                select(Progress.lesson_id).where(
                    Progress.user_id == user_id, Progress.status == "passed"
                )
            )
        ).scalars().all()
    )
    if not passed_ids:
        return {"ok": False, "error": "أكمل درسا أولا لتظهر تحدياتك."}

    lesson_id = random.choice(passed_ids)
    lesson = await session.get(Lesson, lesson_id)
    quiz = await session.scalar(select(Quiz).where(Quiz.lesson_id == lesson_id))
    if not lesson or not quiz:
        return {"ok": False, "error": "لا يوجد اختبار متاح."}

    questions = list(
        (
            await session.execute(
                select(Question).where(Question.quiz_id == quiz.id).order_by(Question.order_index)
            )
        ).scalars().all()
    )
    if not questions:
        return {"ok": False, "error": "لا توجد أسئلة."}

    q = random.choice(questions)
    opts = list(
        (
            await session.execute(
                select(Option).where(Option.question_id == q.id).order_by(Option.order_index)
            )
        ).scalars().all()
    )
    return {
        "ok": True,
        "lesson_id": lesson_id,
        "lesson_title": lesson.title,
        "question_id": q.id,
        "text": q.text,
        "options": [{"id": o.id, "text": o.text, "correct": o.is_correct} for o in opts],
    }


# =============================================================================
#  8. إحصاء المدة (Time Statistics)
# =============================================================================
async def study_statistics(session: AsyncSession, user_id: int) -> dict:
    """إحصاءات عامة عن نشاط المستخدم."""
    from core.models import Attempt, CodeExecution

    total_attempts = await session.scalar(
        select(func.count()).select_from(Attempt).where(Attempt.user_id == user_id)
    ) or 0
    passed_attempts = await session.scalar(
        select(func.count()).select_from(Attempt).where(
            Attempt.user_id == user_id, Attempt.passed.is_(True)
        )
    ) or 0
    avg_score = await session.scalar(
        select(func.avg(Attempt.score)).where(Attempt.user_id == user_id)
    )
    executions = await session.scalar(
        select(func.count()).select_from(CodeExecution).where(CodeExecution.user_id == user_id)
    ) or 0
    lessons_done = await session.scalar(
        select(func.count()).select_from(Progress).where(
            Progress.user_id == user_id, Progress.status == "passed"
        )
    ) or 0

    return {
        "attempts": total_attempts,
        "passed": passed_attempts,
        "success_rate": round(passed_attempts / total_attempts * 100) if total_attempts else 0,
        "avg_score": round(float(avg_score)) if avg_score else 0,
        "executions": executions,
        "lessons_done": lessons_done,
    }


# =============================================================================
#  9. مقارنة مستخدمين (Head-to-Head)
# =============================================================================
async def compare_users(session: AsyncSession, user_a: int, user_b: int) -> dict:
    """مارنة إحصائية بين مستخدمين."""
    async def _stats(uid: int) -> dict:
        u = await session.get(User, uid)
        lessons = await session.scalar(
            select(func.count()).select_from(Progress).where(
                Progress.user_id == uid, Progress.status == "passed"
            )
        ) or 0
        return {
            "xp": u.xp if u else 0,
            "level": u.level if u else 1,
            "streak": u.streak_count if u else 0,
            "lessons": lessons,
            "name": (u.username or f"user{uid}") if u else f"user{uid}",
        }

    a = await _stats(user_a)
    b = await _stats(user_b)
    return {"a": a, "b": b, "winner": "a" if a["xp"] > b["xp"] else ("b" if b["xp"] > a["xp"] else "tie")}
