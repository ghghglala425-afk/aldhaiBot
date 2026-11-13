# -*- coding: utf-8 -*-
"""فحص تكامل **قراءة فقط** لقاعدة الإنتاج (لا يكتب ولا يعدّل شيئا).

يُشغَّل عبر Railway ليرى قاعدة PostgreSQL الحقيقية:

    railway run -- .venv312/Scripts/python.exe scripts/audit_prod.py

يفحص: المحتوى، الاختبارات والخيارات، المسارات، التقدّم والمحاولات،
وتكامل النصوص. يعيد رمز خروج 1 عند وجود أخطاء.
"""
from __future__ import annotations

import asyncio
import os
import re
import sys
from collections import Counter
from pathlib import Path

try:
    ROOT = Path(__file__).resolve().parents[1]
except NameError:  # يُشغَّل عبر exec داخل الحاوية
    ROOT = Path.cwd()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import func, or_, select  # noqa: E402

from core.db import SessionLocal, engine  # noqa: E402
from core.models import (  # noqa: E402
    Attempt,
    Course,
    DailyAssignment,
    Language,
    LearningPath,
    Lesson,
    Option,
    Progress,
    Question,
    Quiz,
    Stage,
    User,
)

ERRORS: list[str] = []
WARNINGS: list[str] = []
INFO: list[str] = []

# أنماط تشير إلى نص بديل فعلي، لا إلى مصطلح تقني مشروع مثل HTML `placeholder`
# أو قيمة JavaScript `undefined` داخل شرح. العلامات الحقيقية تظهر بين قوسين
# أو وحدها في سطر/حقل، أو ككلمات TODO/FIXME الصريحة.
PLACEHOLDERS = re.compile(
    r"[(\[]\s*(?:placeholder|todo|fixme|undefined|قريبا|قريباً)\s*[)\]]"
    r"|\b(?:TODO|FIXME)\b"
    r"|lorem ipsum"
    r"|سيتم إضافة"
    r"|^\s*(?:undefined|placeholder|todo|fixme|قريبا|قريباً)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
MOJIBAKE = re.compile(r"(Ã.|Â.|Ø.|Ù.|â€™|â€œ|â€\x9d|ï»¿)")


def fail(msg: str) -> None:
    ERRORS.append(msg)


def warn(msg: str) -> None:
    WARNINGS.append(msg)


def info(msg: str) -> None:
    INFO.append(msg)


async def _count(s, model) -> int:
    return int(await s.scalar(select(func.count(model.id))) or 0)


async def audit_counts(s) -> None:
    counts = {}
    for name, model in [
        ("languages", Language),
        ("courses", Course),
        ("stages", Stage),
        ("lessons", Lesson),
        ("quizzes", Quiz),
        ("questions", Question),
        ("options", Option),
        ("users", User),
        ("progress", Progress),
        ("attempts", Attempt),
        ("paths", LearningPath),
        ("daily", DailyAssignment),
    ]:
        counts[name] = await _count(s, model)
    info("العدد: " + " · ".join(f"{k}={v}" for k, v in counts.items()))

    if counts["languages"] != 48:
        fail(f"اللغات: {counts['languages']} بدل 48")
    if counts["courses"] == 0:
        fail("لا توجد كورسات")
    if counts["lessons"] == 0:
        fail("لا توجد دروس")
    if counts["quizzes"] == 0:
        fail("لا توجد اختبارات")


async def audit_statuses(s) -> None:
    rows = (
        await s.execute(select(Lesson.status, func.count(Lesson.id)).group_by(Lesson.status))
    ).all()
    info("حالات الدروس: " + " · ".join(f"{k}={v}" for k, v in rows))
    allowed = {"outline", "draft", "verified", "published"}
    for status, n in rows:
        if status not in allowed:
            fail(f"حالة درس غير معروفة: {status!r} ({n} درس)")


async def audit_empty_content(s) -> None:
    stmt = select(Lesson.id, Lesson.slug, Lesson.status).where(
        or_(Lesson.content_md.is_(None), func.trim(Lesson.content_md) == "")
    )
    rows = (await s.execute(stmt)).all()
    by_status = Counter(r.status for r in rows)
    info("دروس بلا محتوى: " + (" · ".join(f"{k}={v}" for k, v in by_status.items()) or "0"))

    published_empty = [r for r in rows if r.status == "published"]
    if published_empty:
        fail(
            f"{len(published_empty)} درس منشور بلا محتوى — أمثلة: "
            + ", ".join(r.slug for r in published_empty[:10])
        )

    no_title = int(
        await s.scalar(
            select(func.count(Lesson.id)).where(
                or_(Lesson.title.is_(None), func.trim(Lesson.title) == "")
            )
        )
        or 0
    )
    if no_title:
        fail(f"{no_title} درس بلا عنوان")


async def audit_published_quiz(s) -> None:
    stmt = (
        select(Lesson.id, Lesson.slug)
        .outerjoin(Quiz, Quiz.lesson_id == Lesson.id)
        .where(Lesson.status == "published", Quiz.id.is_(None))
    )
    rows = (await s.execute(stmt)).all()
    if rows:
        fail(
            f"{len(rows)} درس منشور بلا اختبار — أمثلة: "
            + ", ".join(r.slug for r in rows[:10])
        )
    else:
        info("كل درس منشور له اختبار ✅")


async def audit_quizzes(s) -> None:
    empty = (
        await s.execute(
            select(Quiz.id, Quiz.lesson_id)
            .outerjoin(Question, Question.quiz_id == Quiz.id)
            .where(Question.id.is_(None))
        )
    ).all()
    if empty:
        fail(f"{len(empty)} اختبار بلا أسئلة — أمثلة: quiz={[q.id for q in empty[:10]]}")
    else:
        info("كل اختبار فيه أسئلة ✅")

    qstats = (
        await s.execute(
            select(Question.id, Question.kind, Question.points, Question.text).where(
                Question.kind.in_(("single", "multi"))
            )
        )
    ).all()
    no_correct: list[int] = []
    multi_correct: list[int] = []
    no_options: list[int] = []
    empty_text: list[int] = []
    zero_points = 0
    for q in qstats:
        opts = (
            await s.execute(
                select(Option.id, Option.is_correct, Option.text).where(
                    Option.question_id == q.id
                )
            )
        ).all()
        if not opts:
            no_options.append(q.id)
            continue
        correct = [o for o in opts if o.is_correct]
        if not correct:
            no_correct.append(q.id)
        if len(correct) > 1:
            multi_correct.append(q.id)
        if any(not (o.text or "").strip() for o in opts):
            empty_text.append(q.id)
        if (q.points or 0) <= 0:
            zero_points += 1
        if not (q.text or "").strip():
            empty_text.append(q.id)

    if no_options:
        fail(f"{len(no_options)} سؤال بلا خيارات — أمثلة: {no_options[:10]}")
    if no_correct:
        fail(f"{len(no_correct)} سؤال بلا إجابة صحيحة — أمثلة: {no_correct[:10]}")
    if multi_correct:
        fail(f"{len(multi_correct)} سؤالأحادي بأكثر من إجابة صحيحة — أمثلة: {multi_correct[:10]}")
    if empty_text:
        fail(f"{len(empty_text)} سؤال/خيار بنص فارغ — أمثلة: {empty_text[:10]}")
    if zero_points:
        fail(f"{zero_points} سؤال بدرجات صفر")

    if not (no_options or no_correct or multi_correct or empty_text or zero_points):
        info("كل أسئلة single/multi سليمة ✅")


async def audit_order_duplicates(s) -> None:
    dup_stage = (
        await s.execute(
            select(Lesson.stage_id, Lesson.order_index, func.count(Lesson.id).label("n"))
            .group_by(Lesson.stage_id, Lesson.order_index)
            .having(func.count(Lesson.id) > 1)
        )
    ).all()
    if dup_stage:
        fail(
            f"{len(dup_stage)} تكرار في ترتيب الدروس داخل مرحلة — أمثلة: "
            + str([(r.stage_id, r.order_index, r.n) for r in dup_stage[:10]])
        )
    else:
        info("ترتيب الدروس داخل المراحل فريد ✅")

    dup_stage_order = (
        await s.execute(
            select(Stage.course_id, Stage.order_index, func.count(Stage.id).label("n"))
            .group_by(Stage.course_id, Stage.order_index)
            .having(func.count(Stage.id) > 1)
        )
    ).all()
    if dup_stage_order:
        warn(
            f"{len(dup_stage_order)} تكرار في ترتيب المراحل — أمثلة: "
            + str([(r.course_id, r.order_index) for r in dup_stage_order[:5]])
        )


async def audit_courses(s) -> None:
    rows = (
        await s.execute(
            select(
                Course.id,
                Course.slug,
                Course.title,
                Course.is_published,
                func.count(Stage.id).label("stages"),
            )
            .outerjoin(Stage, Stage.course_id == Course.id)
            .group_by(Course.id)
        )
    ).all()
    empty_published = [r for r in rows if r.is_published and r.stages == 0]
    if empty_published:
        fail(
            f"{len(empty_published)} كورس منشور بلا مراحل — أمثلة: "
            + ", ".join(r.slug for r in empty_published[:10])
        )
    no_lessons = (
        await s.execute(
            select(Course.slug)
            .outerjoin(Stage, Stage.course_id == Course.id)
            .outerjoin(Lesson, Lesson.stage_id == Stage.id)
            .where(Course.is_published.is_(True))
            .group_by(Course.id)
            .having(func.count(Lesson.id) == 0)
        )
    ).all()
    if no_lessons:
        fail(
            f"{len(no_lessons)} كورس منشور بلا دروس — أمثلة: "
            + ", ".join(r.slug for r in no_lessons[:10])
        )
    if not empty_published and not no_lessons:
        info(f"الكورسات المنشورة ({sum(1 for r in rows if r.is_published)}) فيها مراحل ودروس ✅")


async def audit_paths(s) -> None:
    from pipeline.taxonomy import language_course_slug

    paths = list((await s.execute(select(LearningPath))).scalars().all())
    if not paths:
        warn("لا توجد مسارات تعلّمية")
        return
    course_slugs = set(
        (await s.execute(select(Course.slug).where(Course.is_published.is_(True)))).scalars().all()
    )
    for p in paths:
        slugs = list(p.course_slugs or [])
        if not slugs:
            fail(f"مسار «{p.slug}» بلا كورسات")
            continue
        missing = [x for x in slugs if x not in course_slugs]
        if missing:
            fail(f"مسار «{p.slug}» يشير لكورسات غير منشورة/غير موجودة: {missing}")

    # كل لغة من الـ48 يجب أن يكون لها كورس مخطط
    langs = list((await s.execute(select(Language.slug))).scalars().all())
    missing_courses = [lg for lg in langs if language_course_slug(lg) not in course_slugs]
    if missing_courses:
        warn(
            f"{len(missing_courses)} لغة بلا كورس منشور بعد (يُنشأ عند أول فتح): "
            + ", ".join(missing_courses[:10])
        )
    else:
        info("كل اللغات الـ48 لها كورسات منشورة ✅")


async def audit_progress_attempts(s) -> None:
    bad_status = (
        await s.execute(
            select(Progress.status, func.count(Progress.id)).group_by(Progress.status)
        )
    ).all()
    allowed = {"locked", "available", "in_progress", "passed", "failed"}
    for status, n in bad_status:
        if status not in allowed:
            fail(f"حالة تقدّم غير معروفة: {status!r} ({n})")
    info("حالات التقدّم: " + " · ".join(f"{k}={v}" for k, v in bad_status))

    passed_low = int(
        await s.scalar(
            select(func.count(Attempt.id)).where(
                Attempt.passed.is_(True), Attempt.score < 50
            )
        )
        or 0
    )
    if passed_low:
        fail(f"{passed_low} محاولة ناجحة بدرجة أقل من 50 (تعارض مع العتبة)")

    out_of_range = int(
        await s.scalar(
            select(func.count(Attempt.id)).where(
                or_(Attempt.score < 0, Attempt.score > 100)
            )
        )
        or 0
    )
    if out_of_range:
        fail(f"{out_of_range} محاولة بدرجة خارج 0..100")
    if not passed_low and not out_of_range:
        info("درجات المحاولات وحالة النجاح متسقة مع عتبة 50% ✅")

    # تقدّم مكتمل بلا درجة نجاح
    passed_no_score = int(
        await s.scalar(
            select(func.count(Progress.id)).where(
                Progress.status == "passed", func.coalesce(Progress.best_score, 0) < 50
            )
        )
        or 0
    )
    if passed_no_score:
        warn(f"{passed_no_score} تقدّم «passed» بأفضل درجة أقل من 50")

    # مهام يومية لدروس مفقودة
    orphans = int(
        await s.scalar(
            select(func.count(DailyAssignment.id))
            .outerjoin(Lesson, Lesson.id == DailyAssignment.lesson_id)
            .where(Lesson.id.is_(None))
        )
        or 0
    )
    if orphans:
        fail(f"{orphans} مهمة يومية تشير لدرس مفقود")


async def audit_text_integrity(s) -> None:
    rows = (
        await s.execute(
            select(Lesson.id, Lesson.slug, Lesson.content_md, Lesson.summary).where(
                or_(
                    Lesson.status == "published",
                    Lesson.content_md.is_not(None),
                )
            )
        )
    ).all()
    bad_fences: list[str] = []
    placeholders: list[str] = []
    mojibake: list[str] = []
    very_short: list[str] = []
    for r in rows:
        for text in (r.content_md or "", r.summary or ""):
            if not text:
                continue
            if text.count("```") % 2 != 0:
                bad_fences.append(r.slug)
                break
            m = PLACEHOLDERS.search(text)
            if m:
                placeholders.append(f"{r.slug}({m.group(0)})")
                break
            m = MOJIBAKE.search(text)
            if m:
                mojibake.append(f"{r.slug}({m.group(0)})")
                break
        if r.content_md and 0 < len(r.content_md.strip()) < 80:
            very_short.append(r.slug)

    if bad_fences:
        fail(f"{len(bad_fences)} درس بأسوار ``` غير مغلقة — أمثلة: {bad_fences[:10]}")
    if placeholders:
        fail(f"{len(placeholders)} درس بنص بديل — أمثلة: {placeholders[:10]}")
    if mojibake:
        fail(f"{len(mojibake)} درس بتشويه ترميز — أمثلة: {mojibake[:10]}")
    if very_short:
        warn(f"{len(very_short)} درس بمحتوى قصيرا جدا — أمثلة: {very_short[:10]}")
    if not (bad_fences or placeholders or mojibake):
        info("سلامة نصوص الدروس (أسوار/بدائل/ترميز) ✅")


async def audit_users(s) -> None:
    total = int(await s.scalar(select(func.count(User.id))) or 0)
    info(f"المستخدمون: {total}")
    if total:
        bad_path = int(
            await s.scalar(
                select(func.count(User.id))
                .where(User.active_path_slug.is_not(None))
                .outerjoin(LearningPath, LearningPath.slug == User.active_path_slug)
                .where(LearningPath.id.is_(None))
            )
            or 0
        )
        if bad_path:
            fail(f"{bad_path} مستخدم يشير لمسار غير موجود في active_path_slug")


async def main() -> int:
    print(f"== فحص قاعدة الإنتاج (قراءة فقط) ==")
    count = 0
    async with SessionLocal() as s:
        print(f"المحرك: {engine.url.get_backend_name()}")
        if engine.url.get_backend_name() == "sqlite":
            print("⚠️ المحرك SQLite — تأكد أن DATABASE_URL مضبوط في railway run.")

        checks = [
            audit_counts,
            audit_statuses,
            audit_empty_content,
            audit_published_quiz,
            audit_quizzes,
            audit_order_duplicates,
            audit_courses,
            audit_paths,
            audit_progress_attempts,
            audit_text_integrity,
            audit_users,
        ]
        for check in checks:
            try:
                await check(s)
            except Exception as e:  # noqa: BLE001
                fail(f"استثناء في {check.__name__}: {e}")
                raise
            count += 1

    print("\n== المعلومات ==")
    for line in INFO:
        print(f"  • {line}")
    print("\n== التحذيرات ==")
    for line in WARNINGS:
        print(f"  [تحذير] {line}")
    if not WARNINGS:
        print("  (لا شيء)")
    print("\n== الأخطاء ==")
    for line in ERRORS:
        print(f"  [خطأ] {line}")
    if not ERRORS:
        print("  (لا شيء) — كل الفحوص ناجحة ✅")
    print(f"\nعدد الأخطاء: {len(ERRORS)} — التحذيرات: {len(WARNINGS)}")
    return 1 if ERRORS else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
