# -*- coding: utf-8 -*-
"""ميزات احترافية متقدمة للمنصة التعليمية."""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.db import SessionLocal
from core.logging import get_logger
from core.models import (
    CodeSample,
    Course,
    Lesson,
    LessonTimeLog,
    Progress,
    Question,
    Quiz,
    User,
    CodeExecution,
)

log = get_logger("core.features")


# =============================================================================
# 1. نظام تتبع وقت الدرس (Lesson Time Tracking)
# =============================================================================

@dataclass
class LessonTimeStats:
    total_time_seconds: int
    avg_time_per_lesson: float
    longest_session: int
    streak_days: int

async def track_lesson_time(
    session: AsyncSession | None = None,
    user_id: int = 0,
    lesson_id: int = 0,
    duration_seconds: int = 0,
) -> None:
    """تسجيل الوقت المستغرق في الدرس."""
    row = LessonTimeLog(
        user_id=user_id,
        lesson_id=lesson_id,
        duration_seconds=duration_seconds,
    )
    if session is not None:
        session.add(row)
        await session.commit()
        return
    async with SessionLocal() as s:
        s.add(row)
        await s.commit()


async def get_lesson_time_stats(user_id: int, course_id: int | None = None) -> LessonTimeStats:
    """الحصول على إحصائيات الوقت للمستخدم."""
    async with SessionLocal() as s:
        from core.models import LessonTimeLog
        query = select(LessonTimeLog).where(LessonTimeLog.user_id == user_id)
        if course_id:
            # فلترة حسب الكورس
            lesson_ids = await _get_course_lesson_ids(s, course_id)
            query = query.where(LessonTimeLog.lesson_id.in_(lesson_ids))
        logs = list((await s.execute(query)).scalars().all())
    
    if not logs:
        return LessonTimeStats(0, 0.0, 0, 0)
    
    total = sum(l.duration_seconds for l in logs)
    return LessonTimeStats(
        total_time_seconds=total,
        avg_time_per_lesson=total / len(logs),
        longest_session=max(l.duration_seconds for l in logs),
        streak_days=0  # يمكن حسابه من logs
    )


# =============================================================================
# 2. نظام المراجعة المتباعدة (Spaced Repetition / Smart Review)
# =============================================================================

async def schedule_review(user_id: int, lesson_id: int, quality: int) -> None:
    """جدولة المراجعة بناءً على خوارزمية SM-2 المبسطة.
    quality: 0-5 (جودة الاسترجاع: 0=نسيان كامل، 5=استرجاع مثالي)
    """
    async with SessionLocal() as s:
        from core.models import ReviewSchedule
        review = await s.scalar(
            select(ReviewSchedule).where(
                ReviewSchedule.user_id == user_id,
                ReviewSchedule.lesson_id == lesson_id
            )
        )
        if not review:
            review = ReviewSchedule(user_id=user_id, lesson_id=lesson_id)
            s.add(review)
        
        # خوارزمية SM-2 مبسطة
        if quality >= 3:
            review.ease_factor = max(1.3, review.ease_factor + (0.1 - (5 - quality) * 0.08))
            if review.repetition == 0:
                review.interval = 1
            elif review.repetition == 1:
                review.interval = 6
            else:
                review.interval = int(review.interval * review.ease_factor)
            review.repetition += 1
        else:
            review.repetition = 0
            review.interval = 1
            review.ease_factor = max(1.3, review.ease_factor - 0.2)
        
        review.next_review = datetime.utcnow() + timedelta(days=review.interval)
        review.last_quality = quality
        await s.commit()


async def get_due_reviews(user_id: int, limit: int = 10) -> list[dict]:
    """الحصول على الدروس المستحقة للمراجعة."""
    async with SessionLocal() as s:
        from core.models import ReviewSchedule, Lesson
        now = datetime.utcnow()
        reviews = list((await s.execute(
            select(ReviewSchedule, Lesson)
            .join(Lesson, ReviewSchedule.lesson_id == Lesson.id)
            .where(ReviewSchedule.user_id == user_id)
            .where(ReviewSchedule.next_review <= now)
            .order_by(ReviewSchedule.next_review)
            .limit(limit)
        )).all())
        
        return [{"lesson": lesson, "schedule": sched} for sched, lesson in reviews]


# =============================================================================
# 3. إحصائيات متقدمة للتقدم (Advanced Progress Analytics)
# =============================================================================

@dataclass
class ProgressAnalytics:
    total_lessons: int
    completed_lessons: int
    in_progress_lessons: int
    locked_lessons: int
    completion_rate: float
    avg_score: float
    total_xp: int
    current_streak: int
    longest_streak: int
    weak_areas: list[str]  # مواضيع تحتاج تحسين
    strong_areas: list[str]  # مواضيع قوية

async def get_progress_analytics(user_id: int, course_id: int | None = None) -> ProgressAnalytics:
    """تحليلات متقدمة لتقدم المستخدم."""
    async with SessionLocal() as s:
        # إحصائيات أساسية
        progress_query = select(Progress).where(Progress.user_id == user_id)
        if course_id:
            lesson_ids = await _get_course_lesson_ids(s, course_id)
            progress_query = progress_query.where(Progress.lesson_id.in_(lesson_ids))
        
        progress_records = list((await s.execute(progress_query)).scalars().all())
        
        if not progress_records:
            return ProgressAnalytics(0, 0, 0, 0, 0.0, 0.0, 0, 0, 0, [], [])
        
        completed = [p for p in progress_records if p.status == "passed"]
        in_progress = [p for p in progress_records if p.status == "in_progress"]
        locked = len(progress_records) - len(completed) - len(in_progress)
        
        # متوسط الدرجات
        scores = [p.best_score for p in completed if p.best_score]
        avg_score = sum(scores) / len(scores) if scores else 0
        
        # XP الإجمالي
        user = await s.get(User, user_id)
        total_xp = user.xp if user else 0
        
        # تحديد نقاط الضعف والقوة من الاختبارات
        weak_areas = await _get_weak_areas(s, user_id)
        strong_areas = await _get_strong_areas(s, user_id)
        
        # Streaks
        current_streak = user.streak_count if user else 0
        longest_streak = user.longest_streak if hasattr(user, 'longest_streak') else 0
        
        return ProgressAnalytics(
            total_lessons=len(progress_records),
            completed_lessons=len(completed),
            in_progress_lessons=len(in_progress),
            locked_lessons=locked,
            completion_rate=len(completed) / len(progress_records) * 100,
            avg_score=avg_score,
            total_xp=total_xp,
            current_streak=current_streak,
            longest_streak=longest_streak,
            weak_areas=weak_areas,
            strong_areas=strong_areas,
        )


async def _get_weak_areas(session: AsyncSession, user_id: int) -> list[str]:
    """استخراج المواضيع الضعيفة من إجابات الاختبارات الخاطئة."""
    # تنفيذ مبسط - يمكن تطويره أكثر
    return []


async def _get_strong_areas(session: AsyncSession, user_id: int) -> list[str]:
    """استخراج المواضيع القوية من إجابات الاختبارات الصحيحة."""
    return []


async def _get_course_lesson_ids(session: AsyncSession, course_id: int) -> list[int]:
    from core.models import Lesson, Stage
    res = await session.execute(
        select(Lesson.id)
        .join(Stage, Lesson.stage_id == Stage.id)
        .where(Stage.course_id == course_id)
    )
    return [r[0] for r in res.all()]


# =============================================================================
# 4. لوحة تحكم AI (AI Usage Dashboard)
# =============================================================================

@dataclass
class AIDashboardStats:
    total_requests: int
    total_tokens: int
    total_cost_estimate: float
    by_provider: dict[str, dict]
    by_model: dict[str, dict]
    daily_usage: list[dict]
    top_lessons: list[dict]

async def get_ai_dashboard_stats(days: int = 30) -> AIDashboardStats:
    """لوحة تحكم شاملة لاستخدام AI."""
    async with SessionLocal() as s:
        from core.models import AIUsage
        from datetime import date, timedelta
        
        since = date.today() - timedelta(days=days)
        usage = list((await s.execute(
            select(AIUsage).where(AIUsage.day >= since)
        )).scalars().all())
        
        total_requests = sum(u.requests for u in usage)
        total_tokens = sum(u.tokens for u in usage)
        
        by_provider = {}
        for u in usage:
            if u.provider not in by_provider:
                by_provider[u.provider] = {"requests": 0, "tokens": 0, "errors": 0}
            by_provider[u.provider]["requests"] += u.requests
            by_provider[u.provider]["tokens"] += u.tokens
            by_provider[u.provider]["errors"] += u.errors
        
        # تجميع يومي
        daily = {}
        for u in usage:
            day_str = u.day.isoformat()
            if day_str not in daily:
                daily[day_str] = {"requests": 0, "tokens": 0}
            daily[day_str]["requests"] += u.requests
            daily[day_str]["tokens"] += u.tokens
        
        daily_list = [{"date": k, **v} for k, v in sorted(daily.items())]
        
        return AIDashboardStats(
            total_requests=total_requests,
            total_tokens=total_tokens,
            total_cost_estimate=total_tokens * 0.000001,  # تقدير تقريبي
            by_provider=by_provider,
            by_model={},
            daily_usage=daily_list,
            top_lessons=[],
        )


# =============================================================================
# 5. نظام إشارات الكود (Code Execution Metrics)
# =============================================================================

@dataclass
class CodeExecutionMetrics:
    total_executions: int
    successful_executions: int
    failed_executions: int
    avg_execution_time_ms: float
    total_memory_mb: float
    languages_used: dict[str, int]
    common_errors: list[dict]

async def get_execution_metrics(user_id: int | None = None, days: int = 30) -> CodeExecutionMetrics:
    """مقاييس تنفيذ الكود."""
    async with SessionLocal() as s:
        from core.models import CodeExecution
        from datetime import date, timedelta
        
        since = date.today() - timedelta(days=days)
        query = select(CodeExecution).where(CodeExecution.created_at >= since)
        if user_id:
            query = query.where(CodeExecution.user_id == user_id)
        
        executions = list((await s.execute(query)).scalars().all())
        
        if not executions:
            return CodeExecutionMetrics(0, 0, 0, 0.0, 0.0, {}, [])
        
        total = len(executions)
        successful = sum(1 for e in executions if e.status == "ok")
        failed = total - successful
        
        times = [e.execution_time_ms for e in executions if e.execution_time_ms]
        avg_time = sum(times) / len(times) if times else 0
        
        memory = [e.memory_mb for e in executions if e.memory_mb]
        total_memory = sum(memory) if memory else 0
        
        langs = {}
        for e in executions:
            langs[e.language] = langs.get(e.language, 0) + 1
        
        # أخطاء شائعة
        errors = {}
        for e in executions:
            if e.status != "ok" and e.error:
                key = e.error[:100]
                errors[key] = errors.get(key, 0) + 1
        
        common_errors = [
            {"error": k, "count": v} 
            for k, v in sorted(errors.items(), key=lambda x: x[1], reverse=True)[:10]
        ]
        
        return CodeExecutionMetrics(
            total_executions=total,
            successful_executions=successful,
            failed_executions=failed,
            avg_execution_time_ms=avg_time,
            total_memory_mb=total_memory,
            languages_used=langs,
            common_errors=common_errors,
        )


# =============================================================================
# 6. نظام التلميحات الذكية (Smart Hints for Labs)
# =============================================================================

async def get_smart_hint(session: AsyncSession, user_id: int, lab_id: int, current_attempt: int) -> dict:
    """تلميحات ذكية متدرجة بناءً على محاولات المستخدم."""
    from core.models import Lab, Hint
    
    lab = await session.get(Lab, lab_id)
    if not lab:
        return {"ok": False, "error": "المختبر غير موجود."}
    
    # الحصول على التلميحات المتاحة
    hints = list((await session.execute(
        select(Hint).where(Hint.lab_id == lab_id).order_by(Hint.order_index)
    )).scalars().all())
    
    if not hints:
        return {"ok": False, "error": "لا توجد تلميحات متاحة."}
    
    # تحديد التلميح المناسب بناءً على عدد المحاولات
    hint_index = min(current_attempt, len(hints) - 1)
    hint = hints[hint_index]
    
    # خصم النقاط إن كان التلميح مكلفاً
    cost = hint.cost_xp or 0
    return {
        "ok": True,
        "hint": hint.text,
        "cost": cost,
        "hint_number": hint_index + 1,
        "total_hints": len(hints),
    }


# =============================================================================
# 7. نظام المقارنة بين الكود والحل (Code Comparison Tool)
# =============================================================================

async def compare_code_with_solution(user_code: str, solution_code: str, language: str) -> dict:
    """مقارنة كود المستخدم مع الحل النموذجي."""
    import difflib
    
    user_lines = user_code.strip().splitlines()
    solution_lines = solution_code.strip().splitlines()
    
    diff = list(difflib.unified_diff(
        user_lines, solution_lines,
        fromfile='your_code', tofile='solution',
        lineterm=''
    ))
    
    # حساب نسبة التشابه
    matcher = difflib.SequenceMatcher(None, user_code, solution_code)
    similarity = matcher.ratio()
    
    # استخراج الاختلافات الرئيسية
    additions = [line[1:] for line in diff if line.startswith('+') and not line.startswith('+++')]
    deletions = [line[1:] for line in diff if line.startswith('-') and not line.startswith('---')]
    
    return {
        "similarity": round(similarity * 100, 1),
        "additions": additions[:20],
        "deletions": deletions[:20],
        "diff": "\n".join(diff[:50]),
        "is_correct": similarity > 0.95,
    }


# =============================================================================
# 8. نظام التقييم التكيفي (Adaptive Difficulty)
# =============================================================================

async def adjust_difficulty(session: AsyncSession, user_id: int, lesson_id: int) -> str:
    """تعديل صعوبة الدرس القادم بناءً على الأداء."""
    from core.models import Progress, Lesson
    
    # الحصول على سجل التقدم
    prog = await session.scalar(
        select(Progress).where(
            Progress.user_id == user_id,
            Progress.lesson_id == lesson_id
        )
    )
    
    if not prog:
        return "beginner"
    
    # تحليل الأداء
    if prog.best_score >= 90 and prog.attempts_count <= 1:
        return "advanced"
    elif prog.best_score >= 70:
        return "intermediate"
    else:
        return "beginner"


# =============================================================================
# 9. نظام التقييم والردود (Lesson Rating & Feedback)
# =============================================================================

async def rate_lesson(session: AsyncSession, user_id: int, lesson_id: int, rating: int, feedback: str = "") -> dict:
    """تقييم الدرس وإضافة تعليق."""
    from core.models import LessonRating
    
    if not 1 <= rating <= 5:
        return {"ok": False, "error": "التقييم يجب أن يكون بين 1 و 5."}
    
    existing = await session.scalar(
        select(LessonRating).where(
            LessonRating.user_id == user_id,
            LessonRating.lesson_id == lesson_id
        )
    )
    
    if existing:
        existing.rating = rating
        existing.feedback = feedback
    else:
        session.add(LessonRating(
            user_id=user_id,
            lesson_id=lesson_id,
            rating=rating,
            feedback=feedback
        ))
    
    await session.commit()
    return {"ok": True, "message": "شكراً لتقييمك!"}


async def get_lesson_ratings(session: AsyncSession, lesson_id: int) -> dict:
    """الحصول على متوسط تقييم الدرس."""
    from core.models import LessonRating
    from sqlalchemy import func
    
    result = await session.execute(
        select(func.avg(LessonRating.rating), func.count(LessonRating.id))
        .where(LessonRating.lesson_id == lesson_id)
    )
    avg, count = result.one()
    
    return {
        "average_rating": round(avg, 1) if avg else 0,
        "total_ratings": count,
    }


# =============================================================================
# 10. نظام تصدير التقدم (Progress Export)
# =============================================================================

async def export_user_progress(user_id: int, format: str = "json") -> dict:
    """تصدير تقدم المستخدم بصيغة JSON أو PDF."""
    async with SessionLocal() as s:
        user = await s.get(User, user_id)
        if not user:
            return {"error": "المستخدم غير موجود."}
        
        # الحصول على جميع التقدم
        progresses = list((await s.execute(
            select(Progress).where(Progress.user_id == user_id)
        )).scalars().all())
        
        courses = list((await s.execute(
            select(Course).where(Course.is_published.is_(True))
        )).scalars().all())
        
        data = {
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "xp": user.xp,
                "level": user.level,
                "streak_count": user.streak_count,
                "joined_at": user.created_at.isoformat() if user.created_at else None,
            },
            "progress": [
                {
                    "lesson_id": p.lesson_id,
                    "status": p.status,
                    "best_score": p.best_score,
                    "attempts_count": p.attempts_count,
                    "completed_at": p.completed_at.isoformat() if p.completed_at else None,
                }
                for p in progresses
            ],
            "exported_at": datetime.utcnow().isoformat(),
        }
        
        if format == "json":
            return {"format": "json", "data": data}
        else:
            # يمكن إضافة دعم PDF لاحقاً
            return {"error": "صيغة PDF غير مدعومة حالياً."}


# =============================================================================
# 10. سجل تنفيذ الأكواد (Code Execution History)
# =============================================================================

async def log_code_execution(
    session: AsyncSession,
    user_id: int,
    lesson_id: int | None,
    code_id: int | None,
    language: str,
    code: str,
    stdout: str,
    stderr: str,
    status: str,
    execution_time_ms: int,
    memory_mb: float,
    error: str | None = None,
) -> None:
    """تسجيل تنفيذ الكود في السجل."""
    from core.models import CodeExecution
    
    exec_log = CodeExecution(
        user_id=user_id,
        lesson_id=lesson_id,
        code_id=code_id,
        language=language,
        code=code[:10000],  # حد أقصى 10KB
        stdout=stdout[:5000],
        stderr=stderr[:5000],
        status=status,
        execution_time_ms=execution_time_ms,
        memory_mb=memory_mb,
        error=error[:500] if error else None,
    )
    session.add(exec_log)
    await session.commit()


async def get_user_execution_history(
    user_id: int,
    lesson_id: int | None = None,
    limit: int = 50
) -> list[dict]:
    """الحصول على سجل تنفيذ الكود للمستخدم."""
    async with SessionLocal() as s:
        from core.models import CodeExecution
        from datetime import datetime, timedelta
        
        query = select(CodeExecution).where(CodeExecution.user_id == user_id)
        if lesson_id:
            query = query.where(CodeExecution.lesson_id == lesson_id)
        
        executions = list((await s.execute(
            query.order_by(CodeExecution.created_at.desc()).limit(limit)
        )).scalars().all())
        
        return [
            {
                "id": e.id,
                "lesson_id": e.lesson_id,
                "code_id": e.code_id,
                "language": e.language,
                "code": e.code[:200] + "..." if len(e.code) > 200 else e.code,
                "status": e.status,
                "execution_time_ms": e.execution_time_ms,
                "memory_mb": e.memory_mb,
                "error": e.error,
                "created_at": e.created_at.isoformat(),
            }
            for e in executions
        ]


# =============================================================================
# 11. نظام المفضلات للكود (Code Favorites)
# =============================================================================

async def toggle_code_favorite(session: AsyncSession, user_id: int, code_id: int) -> dict:
    """إضافة/إزالة كود من المفضلات."""
    from core.models import CodeFavorite
    
    existing = await session.scalar(
        select(CodeFavorite).where(
            CodeFavorite.user_id == user_id,
            CodeFavorite.code_id == code_id
        )
    )
    
    if existing:
        await session.delete(existing)
        await session.commit()
        return {"ok": True, "favorited": False, "message": "أُزيل من المفضلات."}
    
    session.add(CodeFavorite(user_id=user_id, code_id=code_id))
    await session.commit()
    return {"ok": True, "favorited": True, "message": "أضيف إلى المفضلات!"}


async def get_user_favorite_codes(session: AsyncSession, user_id: int) -> list[dict]:
    """الحصول على أكواد المستخدم المفضلة."""
    from core.models import CodeFavorite, CodeSample
    
    favs = list((await session.execute(
        select(CodeFavorite, CodeSample)
        .join(CodeSample, CodeFavorite.code_id == CodeSample.id)
        .where(CodeFavorite.user_id == user_id)
        .order_by(CodeFavorite.created_at.desc())
    )).all())
    
    return [
        {
            "code_id": code.id,
            "title": code.title,
            "language": code.language,
            "code": code.code[:200] + "..." if len(code.code) > 200 else code.code,
            "favorited_at": fav.created_at.isoformat(),
        }
        for fav, code in favs
    ]


# =============================================================================
# 12. نظام الإشارات المرجعية المحسن (Enhanced Bookmarks)
# =============================================================================

async def add_bookmark_with_note(
    session: AsyncSession,
    user_id: int,
    lesson_id: int,
    note: str = "",
    position: int = 0  # موضع في الدرس (بالمئوية)
) -> dict:
    """إضافة إشارة مرجعية مع ملاحظة وموقع."""
    from core.models import Bookmark
    
    existing = await session.scalar(
        select(Bookmark).where(
            Bookmark.user_id == user_id,
            Bookmark.lesson_id == lesson_id
        )
    )
    
    if existing:
        existing.note = note
        existing.position = position
    else:
        session.add(Bookmark(
            user_id=user_id,
            lesson_id=lesson_id,
            note=note,
            position=position
        ))
    
    await session.commit()
    return {"ok": True, "message": "تم حفظ الإشارة المرجعية."}


async def get_user_bookmarks(session: AsyncSession, user_id: int) -> list[dict]:
    """الحصول على جميع الإشارات المرجعية للمستخدم."""
    from core.models import Bookmark, Lesson
    
    bookmarks = list((await session.execute(
        select(Bookmark, Lesson)
        .join(Lesson, Bookmark.lesson_id == Lesson.id)
        .where(Bookmark.user_id == user_id)
        .order_by(Bookmark.created_at.desc())
    )).all())
    
    return [
        {
            "lesson_id": lesson.id,
            "lesson_title": lesson.title,
            "note": bookmark.note,
            "position": bookmark.position,
            "created_at": bookmark.created_at.isoformat(),
        }
        for bookmark, lesson in bookmarks
    ]


# =============================================================================
# 13. لوحة المتصدرين المحسنة (Enhanced Leaderboard)
# =============================================================================

async def get_leaderboard(
    period: str = "all",  # all, weekly, monthly
    limit: int = 50
) -> list[dict]:
    """لوحة المتصدرين مع فلاتر زمنية."""
    from datetime import date, timedelta
    
    async with SessionLocal() as s:
        since = None
        if period == "weekly":
            since = date.today() - timedelta(weeks=1)
        elif period == "monthly":
            since = date.today() - timedelta(days=30)
        
        query = select(User).where(User.is_active.is_(True)).order_by(User.xp.desc())
        
        if since:
            # تصفية حسب XP المكتسب في الفترة
            # يحتاج تعديل في الاستعلام
            pass
        
        users = list((await s.execute(query.limit(limit))).scalars().all())
        
        return [
            {
                "rank": i + 1,
                "username": u.username or f"User_{u.id}",
                "xp": u.xp,
                "level": u.level,
                "streak": u.streak_count,
            }
            for i, u in enumerate(users)
        ]


# =============================================================================
# 12. خلط أسئلة الاختبار (Quiz Question Shuffle)
# =============================================================================

async def get_shuffled_quiz_questions(session: AsyncSession, quiz_id: int, seed: int | None = None) -> list[Question]:
    """الحصول على أسئلة الاختبار بترتيب عشوائي."""
    import random
    
    questions = list((await session.execute(
        select(Question).where(Question.quiz_id == quiz_id).order_by(Question.order_index)
    )).scalars().all())
    
    if seed:
        random.seed(seed)
    random.shuffle(questions)
    return questions


# =============================================================================
# 13. تصدير التقدم (PDF/JSON Export)
# =============================================================================

async def export_progress_pdf(user_id: int) -> bytes:
    """تصدير التقدم كـ PDF (يحتاج مكتبة خارجية)."""
    # يمكن تنفيذها باستخدام reportlab أو fpdf2
    # للتبسيط، نرجع البيانات كـ JSON
    data = await export_user_progress(user_id, "json")
    return json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')


# =============================================================================
# 14. نظام التبليغ عن المحتوى (Content Reporting)
# =============================================================================

async def report_content(
    session: AsyncSession,
    user_id: int,
    content_type: str,  # lesson, code, quiz, lab
    content_id: int,
    reason: str
) -> dict:
    """التبليغ عن محتوى غير مناسب."""
    from core.models import ContentReport
    
    report = ContentReport(
        user_id=user_id,
        content_type=content_type,
        content_id=content_id,
        reason=reason,
    )
    session.add(report)
    await session.commit()
    return {"ok": True, "message": "تم إرسال البلاغ، شكراً لك."}


# =============================================================================
# 15. نظام البحث المحسن (Enhanced Search with Filters)
# =============================================================================

async def advanced_search(
    session: AsyncSession,
    query: str,
    filters: dict[str, Any],
    limit: int = 20
) -> dict:
    """بحث متقدم مع فلاتر."""
    from sqlalchemy import or_, and_
    
    conditions = []
    if query:
        conditions.append(or_(
            Lesson.title.ilike(f"%{query}%"),
            Lesson.summary.ilike(f"%{query}%"),
            Lesson.content_md.ilike(f"%{query}%"),
            CodeSample.code.ilike(f"%{query}%"),
            CodeSample.title.ilike(f"%{query}%"),
        ))
    
    if filters.get("language"):
        conditions.append(CodeSample.language == filters["language"])
    
    if filters.get("difficulty"):
        conditions.append(Lesson.difficulty == filters["difficulty"])
    
    if filters.get("course_id"):
        conditions.append(Stage.course_id == filters["course_id"])
    
    if filters.get("has_quiz") is not None:
        if filters["has_quiz"]:
            conditions.append(Lesson.quizzes.any())
        else:
            conditions.append(~Lesson.quizzes.any())
    
    if filters.get("has_lab") is not None:
        if filters["has_lab"]:
            conditions.append(Lesson.labs.any())
        else:
            conditions.append(~Lesson.labs.any())
    
    query = select(Lesson).where(and_(*conditions)).limit(limit)
    lessons = list((await session.execute(query)).scalars().all())
    
    return {
        "results": [
            {
                "id": l.id,
                "title": l.title,
                "summary": l.summary,
                "difficulty": l.difficulty,
                "language": l.language_slug,
            }
            for l in lessons
        ],
        "total": len(lessons),
    }


# =============================================================================
# 16. نظام التبديل بين اللغات (Multi-language Support)
# =============================================================================

async def get_user_language(session: AsyncSession, user_id: int) -> str:
    """الحصول على لغة المستخدم المفضلة."""
    user = await session.get(User, user_id)
    return user.preferred_language if user and user.preferred_language else "ar"

async def set_user_language(session: AsyncSession, user_id: int, language: str) -> dict:
    """تعيين لغة المستخدم المفضلة."""
    user = await session.get(User, user_id)
    if not user:
        return {"ok": False, "error": "المستخدم غير موجود."}
    
    supported = ["ar", "en", "fr", "es"]
    if language not in supported:
        return {"ok": False, "error": f"اللغة غير مدعومة. اللغات المدعومة: {supported}"}
    
    user.preferred_language = language
    await session.commit()
    return {"ok": True, "message": f"تم تعيين اللغة إلى {language}."}


# =============================================================================
# 17. نظام الإشعارات الذكية (Smart Notifications)
# =============================================================================

async def send_smart_notification(
    session: AsyncSession,
    user_id: int,
    notification_type: str,
    title: str,
    message: str,
    data: dict | None = None
) -> None:
    """إرسال إشعار ذكي للمستخدم."""
    from core.models import Notification
    
    notification = Notification(
        user_id=user_id,
        type=notification_type,
        title=title,
        message=message,
        data=data or {},
    )
    session.add(notification)
    await session.commit()


async def get_user_notifications(
    session: AsyncSession,
    user_id: int,
    unread_only: bool = False,
    limit: int = 50
) -> list[dict]:
    from core.models import Notification
    
    query = select(Notification).where(Notification.user_id == user_id).order_by(Notification.created_at.desc())
    if unread_only:
        query = query.where(Notification.is_read.is_(False))
    
    notifications = list((await session.execute(query.limit(limit))).scalars().all())
    
    return [
        {
            "id": n.id,
            "type": n.type,
            "title": n.title,
            "message": n.message,
            "data": n.data,
            "is_read": n.is_read,
            "created_at": n.created_at.isoformat(),
        }
        for n in notifications
    ]


async def mark_notification_read(session: AsyncSession, notification_id: int) -> None:
    from core.models import Notification
    notif = await session.get(Notification, notification_id)
    if notif:
        notif.is_read = True
        await session.commit()


# =============================================================================
# 18. نظام نسخ الكود (Code Snippet Sharing)
# =============================================================================

async def share_code_snippet(
    session: AsyncSession,
    user_id: int,
    code_id: int,
    title: str = "",
    is_public: bool = True
) -> dict:
    """مشاركة مقتطف كود برابط قابل للمشاركة."""
    from core.models import CodeShare
    
    # التحقق من وجود الكود
    from core.models import CodeSample
    code = await session.get(CodeSample, code_id)
    if not code:
        return {"ok": False, "error": "الكود غير موجود."}
    
    share = CodeShare(
        user_id=user_id,
        code_id=code_id,
        title=title or code.title,
        is_public=is_public,
    )
    session.add(share)
    await session.commit()
    
    return {
        "ok": True,
        "share_url": f"/share/{share.share_token}",
        "share_token": share.share_token,
    }


# =============================================================================
# 19. نظام التحديات اليومية (Daily Challenges)
# =============================================================================

async def get_daily_challenge(session: AsyncSession, user_id: int) -> dict:
    """الحصول على التحدي اليومي للمستخدم."""
    from core.models import DailyChallenge, DailyChallengeProgress
    from datetime import date
    
    today = date.today()
    challenge = await session.scalar(
        select(DailyChallenge).where(DailyChallenge.date == today)
    )
    
    if not challenge:
        return {"ok": False, "error": "لا يوجد تحدي اليوم."}
    
    progress = await session.scalar(
        select(DailyChallengeProgress).where(
            DailyChallengeProgress.user_id == user_id,
            DailyChallengeProgress.challenge_id == challenge.id
        )
    )
    
    return {
        "ok": True,
        "challenge": {
            "id": challenge.id,
            "title": challenge.title,
            "description": challenge.description,
            "difficulty": challenge.difficulty,
            "xp_reward": challenge.xp_reward,
            "tasks": challenge.tasks,
        },
        "progress": {
            "completed": progress.completed if progress else False,
            "completed_at": progress.completed_at.isoformat() if progress and progress.completed_at else None,
            "score": progress.score if progress else 0,
        } if progress else {"completed": False, "completed_at": None, "score": 0},
    }


# =============================================================================
# 20. نظام التحديات الأسبوعية/الشهرية (Weekly/Monthly Challenges)
# =============================================================================

async def get_active_challenges(session: AsyncSession, user_id: int) -> list[dict]:
    """الحصول على التحديات النشطة للمستخدم."""
    from core.models import WeeklyChallenge, MonthlyChallenge, ChallengeProgress
    from datetime import date, timedelta
    
    today = date.today()
    challenges = []
    
    # التحديات الأسبوعية
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    weekly = await session.scalar(
        select(WeeklyChallenge).where(
            WeeklyChallenge.start_date <= week_end,
            WeeklyChallenge.end_date >= week_start,
        )
    )
    if weekly:
        progress = await session.scalar(
            select(ChallengeProgress).where(
                ChallengeProgress.user_id == user_id,
                ChallengeProgress.challenge_id == weekly.id,
                ChallengeProgress.challenge_type == "weekly"
            )
        )
        challenges.append({
            "type": "weekly",
            "title": weekly.title,
            "description": weekly.description,
            "xp_reward": weekly.xp_reward,
            "progress": progress.current_progress if progress else 0,
            "target": weekly.target,
            "completed": progress.completed if progress else False,
        })
    
    # التحديات الشهرية
    month_start = today.replace(day=1)
    monthly = await session.scalar(
        select(MonthlyChallenge).where(
            MonthlyChallenge.start_date <= today,
            MonthlyChallenge.end_date >= today,
        )
    )
    if monthly:
        progress = await session.scalar(
            select(ChallengeProgress).where(
                ChallengeProgress.user_id == user_id,
                ChallengeProgress.challenge_id == monthly.id,
                ChallengeProgress.challenge_type == "monthly"
            )
        )
        challenges.append({
            "type": "monthly",
            "title": monthly.title,
            "description": monthly.description,
            "xp_reward": monthly.xp_reward,
            "progress": progress.current_progress if progress else 0,
            "target": monthly.target,
            "completed": progress.completed if progress else False,
        })
    
    return challenges