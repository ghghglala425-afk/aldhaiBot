# -*- coding: utf-8 -*-
"""نسخ بيانات المستخدمين احتياطيا واستعادتها."""
from __future__ import annotations

import asyncio
import datetime as dt
import gzip
import json
import uuid

import pytest
from sqlalchemy import delete, select

from core.db import SessionLocal, init_db
from core.models import Course, Language, Lesson, Progress, Stage, User
from pipeline.backup import (
    backup_filename,
    dump_user_data,
    load_backup,
    restore_payload,
    table_counts,
)


def _unique() -> tuple[int, str]:
    """معرّفات فريدة لكل اختبار (قاعدة الاختبار مشتركة بين الملفات)."""
    seed = uuid.uuid4().int
    return 990_000_000 + seed % 1_000_000, f"bk-{seed % 10**10}"


class _Fixture:
    def __init__(self) -> None:
        self.tg_id, self.username = _unique()
        self.lesson_id: int | None = None
        self.user_id: int | None = None

    async def seed(self) -> int:
        await init_db()
        async with SessionLocal() as s:
            lang = Language(slug=f"bk-lang-{self.username[-8:]}", name="Backup Test")
            s.add(lang)
            await s.flush()
            course = Course(
                slug=f"bk-course-{self.username[-8:]}",
                title="Backup Test Course",
                is_published=True,
            )
            s.add(course)
            await s.flush()
            stage = Stage(course_id=course.id, slug="s1", title="Stage 1")
            s.add(stage)
            await s.flush()
            lesson = Lesson(stage_id=stage.id, slug="l1", title="Lesson 1")
            s.add(lesson)
            await s.flush()
            self.lesson_id = lesson.id

            user = User(
                telegram_id=self.tg_id,
                username=self.username,
                created_at=dt.datetime.now(dt.timezone.utc),
            )
            s.add(user)
            await s.commit()
            await s.refresh(user)
            self.user_id = user.id
            s.add(
                Progress(
                    user_id=user.id,
                    lesson_id=lesson.id,
                    status="passed",
                    best_score=80,
                    completed_at=dt.datetime.now(dt.timezone.utc),
                )
            )
            await s.commit()
            return user.id

    async def cleanup_user(self) -> None:
        """يحذف المستخدم وتقدّمه فقط (يبقي المحتوى لاختبار إعادة الاستعادة)."""
        async with SessionLocal() as s:
            if self.user_id:
                await s.execute(delete(Progress).where(Progress.user_id == self.user_id))
            elif self.lesson_id:
                await s.execute(delete(Progress).where(Progress.lesson_id == self.lesson_id))
            await s.execute(delete(User).where(User.telegram_id == self.tg_id))
            await s.commit()

    async def cleanup(self) -> None:
        """يحذف المستخدم ثم محتوى الاختبار (احتراما للمفاتيح الأجنبية)."""
        await self.cleanup_user()
        async with SessionLocal() as s:
            course = await s.scalar(
                select(Course).where(Course.slug == f"bk-course-{self.username[-8:]}")
            )
            if course:
                stage_ids = list(
                    (await s.execute(select(Stage.id).where(Stage.course_id == course.id)))
                    .scalars()
                    .all()
                )
                if stage_ids:
                    await s.execute(delete(Lesson).where(Lesson.stage_id.in_(stage_ids)))
                    await s.execute(delete(Stage).where(Stage.id.in_(stage_ids)))
                await s.execute(delete(Course).where(Course.id == course.id))
            await s.execute(
                delete(Language).where(Language.slug == f"bk-lang-{self.username[-8:]}")
            )
            await s.commit()

    async def exists(self) -> bool:
        async with SessionLocal() as s:
            return bool(await s.scalar(select(User.id).where(User.telegram_id == self.tg_id)))

    async def progress(self):
        async with SessionLocal() as s:
            return await s.scalar(
                select(Progress).where(
                    Progress.user_id == self.user_id,
                    Progress.lesson_id == self.lesson_id,
                )
            )


@pytest.fixture()
def live() -> _Fixture:
    fx = _Fixture()
    asyncio.run(fx.cleanup())
    asyncio.run(fx.seed())
    try:
        yield fx
    finally:
        asyncio.run(fx.cleanup())


class TestBackup:
    def test_roundtrip_restores_deleted_user(self, live: _Fixture) -> None:
        async def _go() -> None:
            blob, counts = await dump_user_data()
            assert blob[:2] == b"\x1f\x8b", "يجب أن تكون النسخة مضغوطة"
            assert counts["users"] >= 1

            await live.cleanup_user()
            assert not await live.exists()

            restored = await restore_payload(load_backup(blob))
            assert restored["users"] >= 1
            assert await live.exists()

            row = await live.progress()
            assert row is not None and row.status == "passed"

        asyncio.run(_go())

    def test_restore_is_idempotent(self, live: _Fixture) -> None:
        async def _go() -> None:
            blob, _ = await dump_user_data()
            payload = load_backup(blob)
            await restore_payload(payload)
            again = await restore_payload(payload)
            assert again["users"] == 0, "الاستعادة الثانية يجب ألا تكرّر الصفوف"

        asyncio.run(_go())

    def test_dry_run_writes_nothing(self, live: _Fixture) -> None:
        async def _go() -> None:
            blob, _ = await dump_user_data()
            await live.cleanup_user()
            await restore_payload(load_backup(blob), dry_run=True)
            assert not await live.exists(), "الفحص يجب ألا يكتب شيئا"

        asyncio.run(_go())

    def test_rejects_invalid_file(self) -> None:
        with pytest.raises(Exception):
            load_backup(b"not a backup")

    def test_filename_is_timestamped(self) -> None:
        name = backup_filename(dt.datetime(2026, 1, 2, 3, 4, tzinfo=dt.timezone.utc))
        assert name == "academy-backup-20260102-0304.json.gz"


class TestCounts:
    def test_table_counts_include_users(self) -> None:
        async def _go() -> dict[str, int]:
            await init_db()
            return await table_counts()

        counts = asyncio.run(_go())
        assert "users" in counts and "progress" in counts
        assert counts["users"] >= 0


class TestPayloadShape:
    def test_dump_contains_all_tables(self) -> None:
        async def _go() -> dict:
            await init_db()
            blob, _ = await dump_user_data()
            return load_backup(blob)

        payload = asyncio.run(_go())
        assert payload["version"] == 1
        assert "created_at" in payload
        for table in ("users", "progress", "notes", "bookmarks", "certificates"):
            assert table in payload["tables"]

    def test_datetimes_serialized_as_iso(self, live: _Fixture) -> None:
        async def _go() -> dict:
            blob, _ = await dump_user_data()
            return json.loads(gzip.decompress(blob))

        payload = asyncio.run(_go())
        users = payload["tables"]["users"]
        assert users, "يجب أن يحتوي ملف النسخة على المستخدم"
        assert isinstance(users[-1]["created_at"], str)
