# -*- coding: utf-8 -*-
"""حفظ المحتوى المُتحقَّق في قاعدة البيانات (كورسات/مراحل/دروس/اختبارات)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.logging import get_logger
from core.models import (
    CodeSample,
    Course,
    Lesson,
    Option,
    Question,
    Quiz,
    Stage,
)
from pipeline.schema import GeneratedLesson
from pipeline.taxonomy import LessonPlan, lesson_slug

log = get_logger("pipeline.store")


async def ensure_course(session: AsyncSession, plan: LessonPlan) -> Course:
    res = await session.execute(select(Course).where(Course.slug == plan.course_slug))
    course = res.scalar_one_or_none()
    if course:
        return course
    is_language = bool(plan.language_name)
    course = Course(
        slug=plan.course_slug,
        title=plan.course_title,
        description=(
            f"مسار شامل لإتقان {plan.language_name}: دروس وأكواد واختبارات."
            if is_language
            else f"مسار عملي في {plan.course_title} — دروس وأكواد واختبارات."
        ),
        track="programming" if is_language else "cybersecurity",
        difficulty="beginner",
        icon=plan.icon,
        order_index=100 if is_language else 10,
        is_published=True,
    )
    session.add(course)
    await session.flush()
    return course


async def ensure_stage(session: AsyncSession, course: Course, plan: LessonPlan) -> Stage:
    res = await session.execute(
        select(Stage).where(Stage.course_id == course.id, Stage.slug == f"stage-{plan.stage_index}")
    )
    stage = res.scalar_one_or_none()
    if stage:
        return stage
    stage = Stage(
        course_id=course.id,
        slug=f"stage-{plan.stage_index}",
        title=plan.stage,
        order_index=plan.stage_index,
        is_published=True,
    )
    session.add(stage)
    await session.flush()
    return stage


async def save_lesson(
    session: AsyncSession,
    plan: LessonPlan,
    lesson: GeneratedLesson,
    *,
    verified: bool,
    publish: bool,
) -> Lesson:
    course = await ensure_course(session, plan)
    stage = await ensure_stage(session, course, plan)
    slug = lesson_slug(plan)

    existing = await session.execute(
        select(Lesson).where(Lesson.stage_id == stage.id, Lesson.slug == slug)
    )
    row = existing.scalar_one_or_none()
    if row is None:
        row = Lesson(stage_id=stage.id, slug=slug, title=lesson.title)
        session.add(row)

    row.title = lesson.title
    row.summary = lesson.summary
    row.objectives = lesson.objectives
    row.content_md = lesson.content_md
    row.language_slug = plan.language
    row.difficulty = lesson.difficulty if lesson.difficulty else plan.difficulty
    row.est_minutes = lesson.est_minutes
    row.order_index = plan.lesson_index
    row.is_verified = verified
    row.status = "published" if (verified and publish) else ("verified" if verified else "draft")
    await session.flush()

    # الأكواد (استبدال كامل)
    old = await session.execute(select(CodeSample).where(CodeSample.lesson_id == row.id))
    for c in old.scalars().all():
        await session.delete(c)
    for i, c in enumerate(lesson.code_samples, start=1):
        session.add(
            CodeSample(
                lesson_id=row.id,
                language=c.language,
                title=c.title,
                code=c.code,
                explanation=c.explanation,
                expected_output=c.expected_output,
                anatomy=[a.model_dump() for a in c.anatomy],
                usages=[u.model_dump() for u in c.usages],
                parameters=[p.model_dump() for p in c.parameters],
                returns=c.returns,
                gotchas=c.gotchas,
                security_notes=c.security_notes,
                related=c.related,
                tags=c.tags,
                order_index=i,
                is_verified=verified,
            )
        )

    # الاختبار (استبدال كامل)
    oldq = await session.execute(select(Quiz).where(Quiz.lesson_id == row.id))
    quiz = oldq.scalar_one_or_none()
    if quiz is None:
        quiz = Quiz(lesson_id=row.id, pass_score=70, shuffle=True)
        session.add(quiz)
        await session.flush()
    else:
        qold = await session.execute(select(Question).where(Question.quiz_id == quiz.id))
        for q in qold.scalars().all():
            await session.delete(q)
        await session.flush()

    for qi, q in enumerate(lesson.quiz_questions, start=1):
        question = Question(
            quiz_id=quiz.id, text=q.text, kind=q.kind, order_index=qi, explanation=q.explanation
        )
        session.add(question)
        await session.flush()
        for oi, opt in enumerate(q.options, start=1):
            session.add(
                Option(question_id=question.id, text=opt.text, is_correct=opt.correct, order_index=oi)
            )

    await session.commit()
    log.info("حُفظ الدرس %s/%s (%s)", plan.course_slug, slug, row.status)
    return row
