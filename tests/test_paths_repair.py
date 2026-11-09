# -*- coding: utf-8 -*-
"""إصلاح مسارات التعلّم: معرّفات قديمة + كورسات ناقصة + تقدّم سليم."""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from core.db import SessionLocal, engine, init_db
from core.models import (
    Base,
    Course,
    Language,
    LearningPath,
    Lesson,
    Stage,
    User,
)
from core.paths import path_progress


def _reset_db() -> None:
    async def _drop() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    asyncio.run(_drop())
    asyncio.run(init_db())


def _seed_legacy() -> None:
    async def _go() -> None:
        async with SessionLocal() as s:
            for slug, name in [
                ("python", "بايثون"),
                ("javascript", "جافاسكربت"),
                ("php", "PHP"),
                ("sql", "SQL"),
                ("bash", "باش"),
                ("c", "C"),
            ]:
                s.add(Language(slug=slug, name=name, name_ar=name))
            # الكورس التجريبي القديم الذي كان المسار يشير إليه
            demo = Course(
                slug="python-security", title="بايثون للأمن", order_index=1,
                is_published=True,
            )
            s.add(demo)
            await s.flush()
            stage = Stage(
                course_id=demo.id, slug="basics", title="الأساسيات",
                order_index=1, is_published=True,
            )
            s.add(stage)
            await s.flush()
            s.add(
                Lesson(
                    stage_id=stage.id, slug="hello-security", title="مرحبا",
                    summary="م", objectives=["أ"], content_md="ن" * 120,
                    order_index=1, status="published",
                )
            )
            for slug, title, order, courses in [
                ("web-hacking", "الويب", 1,
                 ["javascript-security", "php-security", "sql-security"]),
                ("offensive-python", "بايثون الهجومي", 2,
                 ["python-security", "bash-security"]),
                ("memory-exploitation", "الذاكرة", 3,
                 ["c-security", "python-security"]),
            ]:
                s.add(
                    LearningPath(
                        slug=slug, title=title, description="د", icon="🛤️",
                        order=order, course_slugs=courses,
                    )
                )
            await s.commit()

    asyncio.run(_go())


def test_default_paths_use_real_course_slugs() -> None:
    from pipeline.seed import DEFAULT_PATHS, PATH_COURSE_ALIASES

    for spec in DEFAULT_PATHS:
        assert spec["course_slugs"], spec["slug"]
        for slug in spec["course_slugs"]:
            assert slug.endswith("-mastery"), (spec["slug"], slug)
            assert not slug.endswith("-security")
    assert PATH_COURSE_ALIASES["python-security"] == "python-mastery"


def test_repair_updates_legacy_paths_and_creates_courses() -> None:
    _reset_db()
    try:
        _seed_legacy()

        from pipeline.seed import repair_learning_paths

        changed = asyncio.run(repair_learning_paths(per_stage=1))
        assert changed == 3

        async def _go() -> tuple[dict[str, list[str]], set[str]]:
            async with SessionLocal() as s:
                paths = list((await s.execute(select(LearningPath))).scalars().all())
                mapping = {p.slug: list(p.course_slugs or []) for p in paths}
                courses = set(
                    (await s.execute(select(Course.slug))).scalars().all()
                )
                return mapping, courses

        mapping, courses = asyncio.run(_go())
        assert mapping["web-hacking"] == [
            "javascript-mastery", "php-mastery", "sql-mastery",
        ]
        assert mapping["offensive-python"] == [
            "python-mastery", "bash-mastery",
        ]
        assert mapping["memory-exploitation"] == [
            "c-mastery", "python-mastery",
        ]
        for slugs in mapping.values():
            assert set(slugs) <= courses, (slugs, courses)

        # إعادة التشغيل لا تغيّر شيئا ولا تنشئ كورسات مكررة
        assert asyncio.run(repair_learning_paths(per_stage=1)) == 0
    finally:
        _reset_db()


def test_path_progress_counts_only_openable_lessons() -> None:
    _reset_db()
    try:
        _seed_legacy()

        from pipeline.seed import repair_learning_paths

        asyncio.run(repair_learning_paths(per_stage=1))

        async def _progress() -> dict:
            async with SessionLocal() as s:
                user = User(telegram_id=777001, username="path_user")
                s.add(user)
                await s.flush()
                path = await s.scalar(
                    select(LearningPath).where(LearningPath.slug == "web-hacking")
                )
                data = await path_progress(s, user, path)
                # درس draft لا يُحتسب في المسار
                course = await s.scalar(
                    select(Course).where(Course.slug == "javascript-mastery")
                )
                stage = await s.scalar(
                    select(Stage).where(Stage.course_id == course.id)
                )
                s.add(
                    Lesson(
                        stage_id=stage.id, slug="draft-x", title="مسودة",
                        order_index=999, status="draft",
                    )
                )
                await s.commit()
                data2 = await path_progress(s, user, path)
                assert data["total"] > 0
                assert data2["total"] == data["total"]
                assert data["passed"] == 0 and data["percent"] == 0
                return data

        data = asyncio.run(_progress())
        assert data["total"] > 0
    finally:
        _reset_db()
