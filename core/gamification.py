# -*- coding: utf-8 -*-
"""منطق التلعيب: النقاط، المستويات، السلاسل اليومية، الشارات، الصدارة، الملاحظات."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.logging import get_logger
from core.models import (
    Badge,
    Bookmark,
    Lesson,
    Note,
    Progress,
    Submission,
    User,
    UserBadge,
)
from core.repo import add_xp

log = get_logger("core.gamification")

# تُزرع هذه الشارات في pipeline.seed
BADGE_DEFS = [
    ("first_lesson", "أول خطوة", "أكملت أول درس", "🌱"),
    ("ten_lessons", "مثابر", "أكملت 10 دروس", "📚"),
    ("fifty_lessons", "خبير", "أكملت 50 درسًا", "🎓"),
    ("streak_7", "أسبوع متواصل", "7 أيام متتالية", "🔥"),
    ("streak_30", "شهر من الالتزام", "30 يومًا متتالية", "🏅"),
    ("xp_1000", "جامع النقاط", "وصلت 1000 نقطة", "⭐"),
    ("lab_first", "مخترق مبتدئ", "حلّلت أول مختبر", "🧪"),
    ("lab_ten", "صياد الأعلام", "حلّلت 10 مختبرات", "🏴"),
]


async def award_badge(session: AsyncSession, user: User, slug: str) -> bool:
    badge = await session.scalar(select(Badge).where(Badge.slug == slug))
    if not badge:
        return False
    exists = await session.scalar(
        select(UserBadge).where(UserBadge.user_id == user.id, UserBadge.badge_id == badge.id)
    )
    if exists:
        return False
    session.add(UserBadge(user_id=user.id, badge_id=badge.id))
    await session.commit()
    log.info("شارة %s للمستخدم %s", slug, user.id)
    return True


async def update_streak(session: AsyncSession, user: User) -> int:
    """يحدّث سلسلة الأيام عند إتمام نشاط. يمنع الاحتساب المزدوج في نفس اليوم."""
    today = dt.date.today()
    if user.last_streak_date == today:
        return user.streak_count
    if user.last_streak_date == today - dt.timedelta(days=1):
        user.streak_count = (user.streak_count or 0) + 1
    else:
        user.streak_count = 1
    user.last_streak_date = today
    await session.commit()
    return user.streak_count


async def passed_count(session: AsyncSession, user_id: int) -> int:
    return await session.scalar(
        select(func.count()).select_from(Progress).where(
            Progress.user_id == user_id, Progress.status == "passed"
        )
    ) or 0


async def solved_labs_count(session: AsyncSession, user_id: int) -> int:
    return await session.scalar(
        select(func.count()).select_from(Submission).where(
            Submission.user_id == user_id, Submission.is_correct.is_(True)
        )
    ) or 0


async def evaluate_badges(session: AsyncSession, user: User) -> list[str]:
    """يمنح الشارات المستحقة ويُرجع الجديدة."""
    earned: list[str] = []
    passed = await passed_count(session, user.id)
    labs = await solved_labs_count(session, user.id)

    checks = [
        ("first_lesson", passed >= 1),
        ("ten_lessons", passed >= 10),
        ("fifty_lessons", passed >= 50),
        ("streak_7", (user.streak_count or 0) >= 7),
        ("streak_30", (user.streak_count or 0) >= 30),
        ("xp_1000", (user.xp or 0) >= 1000),
        ("lab_first", labs >= 1),
        ("lab_ten", labs >= 10),
    ]
    for slug, ok in checks:
        if ok and await award_badge(session, user, slug):
            earned.append(slug)
    return earned


async def xp_leaderboard(session: AsyncSession, limit: int = 10) -> list[dict]:
    res = await session.execute(
        select(User).where(User.role != "admin").order_by(desc(User.xp)).limit(limit)
    )
    out = []
    for i, u in enumerate(res.scalars().all(), start=1):
        out.append({"rank": i, "name": u.username or (u.email or "طالب")[:12], "xp": u.xp})
    return out


async def user_rank(session: AsyncSession, user: User) -> int:
    higher = await session.scalar(
        select(func.count()).select_from(User).where(User.xp > (user.xp or 0))
    )
    return (higher or 0) + 1


# ---------------------------------------------------------------------
#  الملاحظات والمرجعيات
# ---------------------------------------------------------------------
async def add_note(session: AsyncSession, user_id: int, lesson_id: int, text: str) -> Note:
    note = Note(user_id=user_id, lesson_id=lesson_id, text=text)
    session.add(note)
    await session.commit()
    await session.refresh(note)
    return note


async def list_notes(session: AsyncSession, user_id: int, limit: int = 20) -> list[Note]:
    res = await session.execute(
        select(Note).where(Note.user_id == user_id).order_by(desc(Note.created_at)).limit(limit)
    )
    return list(res.scalars().all())


async def toggle_bookmark(session: AsyncSession, user_id: int, lesson_id: int) -> bool:
    existing = await session.scalar(
        select(Bookmark).where(Bookmark.user_id == user_id, Bookmark.lesson_id == lesson_id)
    )
    if existing:
        await session.delete(existing)
        await session.commit()
        return False
    session.add(Bookmark(user_id=user_id, lesson_id=lesson_id))
    await session.commit()
    return True


async def list_bookmarks(session: AsyncSession, user_id: int, limit: int = 20) -> list[dict]:
    res = await session.execute(
        select(Bookmark, Lesson)
        .join(Lesson, Bookmark.lesson_id == Lesson.id)
        .where(Bookmark.user_id == user_id)
        .order_by(desc(Bookmark.created_at))
        .limit(limit)
    )
    return [{"lesson_id": l.id, "title": l.title} for _, l in res.all()]
