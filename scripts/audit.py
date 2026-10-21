# -*- coding: utf-8 -*-
"""فحص ذاتي شامل للبوت والمحتوى (بلا شبكة وبلا AI).

**لا ينفّذ أي كود على جهازك:** أي فحص لتشغيل الأكواد يتم داخل Docker فقط؛
وإن غاب Docker يُتخطّى التنفيذ بالكامل مع تحذير.

يشغّل قاعدة بيانات SQLite مؤقتة، يبذرها، ثم يفحص:
  1) كل اللغات (48) وكل الدروس (200/لغة) في المخطط.
  2) محتوى الدرس التجريبي: الاختبارات والإجابات والأكواد القابلة للتشغيل.
  3) رحلة مستخدم كاملة: فتح درس، اختبار صحيح/خاطئ، فتح التالي، درس اليوم، تمرين كود.
  4) سلامة النصوص: أسوار أكواد غير مغلقة، نصوص بديلة، تشويه ترميز.

الاستخدام:
    python scripts/audit.py            # تقرير فقط، رمز خروج 1 عند وجود مشاكل
    python scripts/audit.py --keep     # يبقي قاعدة البيانات المؤقتة للفحص
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ERRORS: list[str] = []
WARNINGS: list[str] = []


def fail(msg: str) -> None:
    ERRORS.append(msg)


def warn(msg: str) -> None:
    WARNINGS.append(msg)


def check(cond: bool, msg: str) -> bool:
    if not cond:
        fail(msg)
    return cond


PLACEHOLDERS = re.compile(r"\b(TODO|FIXME|undefined|NaN|\[object Object\])\b|\?\?\?")
MOJIBAKE = re.compile(r"[ÃÂØÙ][\x80-\xbf]?|�")

# ---------------------------------------------------------------------
# 1) المخطط (تايلات الدروس لكل اللغات)
# ---------------------------------------------------------------------


def audit_taxonomy() -> None:
    from collections import Counter

    from pipeline.languages_data import LANGUAGES
    from pipeline.taxonomy import iter_language_lessons

    if not check(len(LANGUAGES) == 48, f"عدد اللغات {len(LANGUAGES)} بدل 48"):
        return

    for lang in LANGUAGES:
        slug = lang["slug"]
        name = lang.get("name_ar") or lang.get("name") or slug
        plans = iter_language_lessons(slug, name)
        if not check(len(plans) == 200, f"{slug}: عدد الدروس {len(plans)} بدل 200"):
            continue
        keys = [(p.stage_index, p.lesson_index) for p in plans]
        if len(keys) != len(set(keys)):
            fail(f"{slug}: مفاتيح (مرحلة، ترتيب) مكررة")
        titles = [p.outline_title or p.topic for p in plans]
        dups = [t for t, n in Counter(titles).items() if n > 1]
        if dups:
            fail(f"{slug}: عناوين مكررة ({len(dups)}) مثال: {dups[0]!r}")
        if any(not t.strip() for t in titles):
            fail(f"{slug}: عنوان درس فارغ")
        empty_topic = sum(1 for p in plans if not (p.topic or "").strip())
        if empty_topic:
            fail(f"{slug}: {empty_topic} درس بلا موضوع")
        stage_numbers = sorted({p.stage_index for p in plans})
        if stage_numbers != list(range(1, len(stage_numbers) + 1)):
            fail(f"{slug}: ترقيم المراحل غير متصل: {stage_numbers[:5]}…")
        bad_slug = [p for p in plans if not re.fullmatch(r"[\w\-]+", p.slug or "")]
        if bad_slug:
            fail(f"{slug}: {len(bad_slug)} معرف درس غير صالح مثال: {bad_slug[0].slug!r}")


# ---------------------------------------------------------------------
# 2) قاعدة البيانات بعد البذر + محتوى الدرس التجريبي
# ---------------------------------------------------------------------


async def audit_seed() -> dict:
    from sqlalchemy import func, select

    from core.db import SessionLocal
    from core.models import (
        CodeSample,
        Course,
        Language,
        Lesson,
        Option,
        Question,
        Quiz,
        Stage,
    )
    from pipeline import seed

    await seed.main()

    info: dict = {}
    async with SessionLocal() as s:
        counts = {}
        for name, model in [
            ("languages", Language),
            ("courses", Course),
            ("stages", Stage),
            ("lessons", Lesson),
            ("codes", CodeSample),
            ("quizzes", Quiz),
            ("questions", Question),
            ("options", Option),
        ]:
            counts[name] = int(await s.scalar(select(func.count(model.id))) or 0)
        info["counts"] = counts
        check(counts["languages"] == 48, f"قاعدة البيانات: {counts['languages']} لغة بدل 48")
        check(counts["lessons"] >= 1, "قاعدة البيانات: لا توجد دروس بعد البذر")

        demo = await s.scalar(select(Lesson).where(Lesson.slug == "hello-security"))
        if not check(demo is not None, "الدرس التجريبي hello-security غير موجود"):
            return info
        info["demo_id"] = demo.id
        check(bool(demo.content_md and demo.content_md.strip()), "الدرس التجريبي بلا محتوى")
        check(bool(demo.title and demo.title.strip()), "الدرس التجريبي بلا عنوان")
        check(len(demo.objectives or []) >= 3, "الدرس التجريبي بلا أهداف كافية")

        quiz = await s.scalar(select(Quiz).where(Quiz.lesson_id == demo.id))
        if not check(quiz is not None, "الدرس التجريبي بلا اختبار"):
            return info
        questions = list(
            (await s.execute(
                select(Question).where(Question.quiz_id == quiz.id).order_by(Question.order_index)
            )).scalars().all()
        )
        check(len(questions) >= 2, "اختبار الدرس التجريبي أقل من سؤالين")
        total_points = 0
        for q in questions:
            opts = list(
                (await s.execute(select(Option).where(Option.question_id == q.id))).scalars().all()
            )
            total_points += q.points or 0
            if not check(len(opts) >= 2, f"سؤال {q.id} أقل من خيارين"):
                continue
            correct = [o for o in opts if o.is_correct]
            if q.kind in {"single", "multi"}:
                check(len(correct) == 1, f"سؤال {q.id} ({q.kind}): {len(correct)} إجابة صحيحة بدل 1")
            check(all((o.text or "").strip() for o in opts), f"سؤال {q.id} فيه خيار فارغ")
            texts = [o.text for o in opts]
            if len(texts) != len(set(texts)):
                warn(f"سؤال {q.id} فيه خيارات نصية مكررة")
        check(total_points > 0, "مجموع درجات الاختبار صفر")

        codes = list(
            (await s.execute(
                select(CodeSample).where(CodeSample.lesson_id == demo.id).order_by(CodeSample.order_index)
            )).scalars().all()
        )
        info["demo_codes"] = codes
        check(len(codes) >= 5, f"الدرس التجريبي فيه {len(codes)} كود فقط")
        for c in codes:
            label = f"كود {c.id} ({c.title!r})"
            check(bool((c.code or "").strip()), f"{label}: نص فارغ")
            check(bool((c.language or "").strip()), f"{label}: لغة غير محددة")
            fences = (c.code or "").count("```")
            check(fences % 2 == 0, f"{label}: أسوار أكواد غير متوازنة")

        # سلامة نصوص الشرح
        for text, label in [(demo.content_md, "content_md"), (demo.summary, "summary")]:
            if text:
                check(text.count("```") % 2 == 0, f"الدرس التجريبي: {label} فيه أسوار غير مغلقة")
                m = PLACEHOLDERS.search(text)
                if m:
                    fail(f"الدرس التجريبي: {label} يحتوي نصا بديلا {m.group(0)!r}")
                m = MOJIBAKE.search(text)
                if m:
                    fail(f"الدرس التجريبي: {label} فيه تشويه ترميز {m.group(0)!r}")

    info["demo_quiz"] = (quiz, questions)

    # تشغيل أكواد الدرس التجريبي — داخل Docker فقط، ولا شيء على المضيف
    from pipeline.sandbox_runner import _RUN, docker_available, run_code

    docker_ok = await docker_available()
    if not docker_ok:
        warn(
            "Docker غير متاح — تم تخطي تنفيذ الأكواد تماما. "
            "هذا الفحص لا يشغّل أي كود على جهازك."
        )
    for c in (info["demo_codes"] if docker_ok else []):
        if (c.language or "").lower() not in _RUN:
            fail(f"كود {c.id}: لغة {c.language!r} غير مدعومة في المنفّذ")
            continue
        try:
            res = await run_code(c.language, c.code, exec_enabled=True, timeout=10)
        except Exception as e:  # noqa: BLE001
            fail(f"كود {c.id} ({c.title!r}): استثناء تشغيل: {e}")
            continue
        if res.status != "ok":
            fail(
                f"كود {c.id} ({c.title!r}): الحالة {res.status} — "
                f"{(res.detail or res.stderr or '')[:200]}"
            )
        elif not (res.stdout or "").strip():
            warn(f"كود {c.id} ({c.title!r}): لا يطبع أي خرج")

    return info


# ---------------------------------------------------------------------
# 3) رحلة مستخدم كاملة
# ---------------------------------------------------------------------


async def audit_journey(info: dict) -> None:
    from sqlalchemy import select

    from core.db import SessionLocal
    from core.learning import (
        STATUS_PASSED,
        is_unlocked,
        lesson_day,
        maybe_certificate,
        next_lesson_id,
        ordered_lessons,
        start_lesson,
        submit_quiz,
        todays_daily,
    )
    from core.models import Course, Lesson, Option, Question, Quiz, Stage, User
    from pipeline.outline import outline_language_slug
    from pipeline.taxonomy import language_course_slug

    async with SessionLocal() as s:
        # مستخدم جديد
        user = User(telegram_id=999000111, username="audit_user", locale="ar")
        s.add(user)
        await s.commit()
        await s.refresh(user)

        # بناء مخطط لغة محليا (بلا AI) كما يفعل البوت عند فتح اللغة
        await outline_language_slug(s, "python", use_ai=False)
        course = await s.scalar(select(Course).where(Course.slug == language_course_slug("python")))
        if not check(course is not None, "فشل بناء مخطط لغة بايثون محليا"):
            return
        lessons = await ordered_lessons(s, course.id)
        check(len(lessons) == 200, f"مخطط بايثون: {len(lessons)} درس بدل 200")
        stages = list(
            (await s.execute(select(Stage).where(Stage.course_id == course.id))).scalars().all()
        )
        check(len(stages) == 10, f"مخطط بايثون: {len(stages)} مرحلة بدل 10")
        check(all(l.status == "outline" for l in lessons), "دروس المخطط ليست بحالة outline")
        for l in lessons:
            if not (l.title or "").strip():
                fail(f"درس مخطط بلا عنوان: {l.id}")
                break
        finder = {l.id: l for l in lessons}
        first, second = lessons[0], lessons[1]
        check(await is_unlocked(s, user, first), "الدرس الأول مقفل على مستخدم جديد")
        check(not await is_unlocked(s, user, second), "الدرس الثاني مفتوح قبل إكمال الأول")
        check(await lesson_day(s, first) == 1, "ترقيم اليوم للدرس الأول ليس 1")
        check(await lesson_day(s, second) == 2, "ترقيم اليوم للدرس الثاني ليس 2")
        check(await next_lesson_id(s, first) == second.id, "الدرس التالي غير صحيح")

        # اختبار غير موجود على درس مخطط: يجب خطأ نظيف بلا استثناء
        res = await submit_quiz(s, user, first, {})
        check(res.get("ok") is False, "اختبار درس مخطط لم يُرجع خطأ نظيفا")

        await start_lesson(s, user.id, first.id)

        # درس اليوم ثابت خلال نفس اليوم
        daily1 = await todays_daily(s, user)
        daily2 = await todays_daily(s, user)
        check(daily1 is not None, "درس اليوم غير متاح")
        check(daily1 and daily2 and daily1.id == daily2.id, "درس اليوم غير ثابت خلال اليوم")

    # اختبار الدرس التجريبي: إجابات صحيحة ثم خاطئة
    async with SessionLocal() as s:
        user = await s.scalar(select(User).where(User.telegram_id == 999000111))
        demo = await s.get(Lesson, info["demo_id"])
        if not check(demo is not None, "الدرس التجريبي مفقود في رحلة المستخدم"):
            return
        quiz = await s.scalar(select(Quiz).where(Quiz.lesson_id == demo.id))
        questions = list(
            (await s.execute(select(Question).where(Question.quiz_id == quiz.id))).scalars().all()
        )
        correct: dict[int, list[int]] = {}
        wrong: dict[int, list[int]] = {}
        for q in questions:
            opts = list(
                (await s.execute(select(Option).where(Option.question_id == q.id))).scalars().all()
            )
            correct[q.id] = [o.id for o in opts if o.is_correct]
            wrong[q.id] = [o.id for o in opts if not o.is_correct][:1]

        bad = await submit_quiz(s, user, demo, wrong)
        check(bad.get("ok") is True and bad.get("score") == 0, "إجابات خاطئة لم تُسجّل 0")
        check(bad.get("passed") is False, "إجابات خاطئة نجحت في الاختبار")

        good = await submit_quiz(s, user, demo, correct)
        check(good.get("ok") is True, f"اختبار صحيح رجع خطأ: {good.get('error')}")
        check(good.get("score") == 100, f"درجة الاختبار الصحيح {good.get('score')} بدل 100")
        check(good.get("passed") is True, "الاختبار الصحيح لم يُعتبر ناجحا")

        from core.models import Progress

        prog = await s.scalar(
            select(Progress).where(Progress.user_id == user.id, Progress.lesson_id == demo.id)
        )
        check(prog is not None and prog.status == STATUS_PASSED, "حالة التقدم بعد النجاح غير passed")

        # الكورس التجريبي فيه درس واحد: النجاح فيه يجب أن يمنح شهادة
        stage = await s.get(Stage, demo.stage_id)
        cert = await maybe_certificate(s, user, stage.course_id) if stage else None
        check(cert is not None and bool(cert.code), "لم تُصدر شهادة بعد إكمال الكورس التجريبي")

        # تمرين الكود: تشغيل الحل المرجعي داخل Docker ومطابقته لنفسه
        from app.handlers.exercise import _is_correct, _norm, _pick_reference
        from pipeline.sandbox_runner import docker_available, run_code

        ref = await _pick_reference(s, demo.id)
        if check(ref is not None, "لا يوجد كود مرجعي للتمرين") and await docker_available():
            probe = await run_code(ref.language, ref.code, exec_enabled=True, timeout=10)
            if probe.status == "ok":
                text = _norm(probe.stdout)
                check(_is_correct(text, text), "دالة مقارنة الإجابة لا تقبل الخرج نفسه")
                check(_norm("a\r\nb\r\n") == "a\nb", "تطبيع أسطر ويندوز فشل")
                if not text.strip():
                    warn("الخرج المرجعي للتمرين فارغ — التقييم سيكون بوضع المراجعة")


# ---------------------------------------------------------------------
# 4) التقرير
# ---------------------------------------------------------------------


async def run(keep: bool) -> int:
    tmp = Path(tempfile.mkdtemp(prefix="bot_audit_"))
    db = tmp / "audit.db"
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db.as_posix()}"
    os.environ["VERIFY_EXEC"] = "0"
    os.environ["AI_API_KEY"] = ""
    os.environ["AI_FREE_MODE"] = "0"

    print("== فحص المخطط ==")
    try:
        audit_taxonomy()
    except Exception:
        fail("استثناء في فحص المخطط:\n" + traceback.format_exc())

    print("== بذر قاعدة مؤقتة وفحص المحتوى ==")
    info: dict = {}
    try:
        info = await audit_seed()
    except Exception:
        fail("استثناء في فحص البذر:\n" + traceback.format_exc())

    print("== محاكاة رحلة مستخدم ==")
    if info.get("demo_id"):
        try:
            await audit_journey(info)
        except Exception:
            fail("استثناء في رحلة المستخدم:\n" + traceback.format_exc())
    else:
        fail("تخطّي رحلة المستخدم لغياب الدرس التجريبي")

    print("\n== النتيجة ==")
    for w in WARNINGS:
        print(f"  [تحذير] {w}")
    for e in ERRORS:
        print(f"  [خطأ] {e}")
    print(f"عدد الأخطاء: {len(ERRORS)} — التحذيرات: {len(WARNINGS)}")
    if keep:
        print(f"قاعدة البيانات المؤقتة: {db}")
    else:
        try:
            db.unlink(missing_ok=True)
            tmp.rmdir()
        except OSError:
            pass
    return 1 if ERRORS else 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true", help="إبقاء قاعدة البيانات المؤقتة")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.keep)))


if __name__ == "__main__":
    main()
