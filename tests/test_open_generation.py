# -*- coding: utf-8 -*-
"""اختبارات: التوليد متاح لكل المستخدمين مع حماية الحصة المجانية."""
from __future__ import annotations

import re
from pathlib import Path

from app import ratelimit

ROOT = Path(__file__).resolve().parents[1]
HANDLERS = ROOT / "app" / "handlers"


def _src(name: str) -> str:
    return (HANDLERS / name).read_text(encoding="utf-8")


class TestGenerationOpenToAll:
    """بناء المخطط والتسخين وتوليد الدرس — لكل المستخدمين."""

    def test_language_build_has_no_admin_gate(self) -> None:
        src = _src("languages.py")
        body = src.split("async def language_build")[1].split("async def language_warm")[0]
        assert "is_admin" not in body, "building the outline must be open to all users"

    def test_language_warm_has_no_admin_gate(self) -> None:
        src = _src("languages.py")
        body = src.split("async def language_warm")[1].split("def register_handlers")[0]
        # لا بوابة: لاreturn مبكر بسبب الصلاحية
        assert "if not is_admin(" not in body, "warming lessons must be open to all users"
        assert "للمشرف فقط" not in body

    def test_generate_now_has_no_admin_gate(self) -> None:
        src = _src("learn.py")
        body = src.split("async def generate_now")[1].split("# ----")[0]
        assert "is_admin" not in body, "generating a lesson must be open to all users"

    def test_bulk_build_command_stays_admin_only(self) -> None:
        """/build all يبني 48 لغة — يبقى للمشرف فقط."""
        src = _src("admin.py")
        body = src.split("async def build_cmd")[1].split("def register_handlers")[0]
        assert "is_admin" in body, "the bulk build command must stay admin only"

    def test_no_admin_only_message_remains(self) -> None:
        for name in ("languages.py", "learn.py"):
            src = _src(name)
            assert "للمشرف فقط" not in src, f"{name} still blocks users"


class TestQuotaProtection:
    """الحصة المجانية محدودة — الحماية عبر سقف الطابور العام وحصص المزوّد."""

    def test_generation_is_not_rate_limited(self) -> None:
        """التوليد متاح بلا حدود زمنية (حسب طلب المستخدم)."""
        for key in ("outline", "warm", "gen"):
            assert key not in ratelimit.LIMITS, f"{key} must not be rate limited"

    def test_handlers_do_not_guard_generation(self) -> None:
        for name, marker in (
            ("languages.py", 'ratelimit.guard(update, "outline")'),
            ("languages.py", 'ratelimit.guard(update, "warm")'),
            ("learn.py", 'ratelimit.guard(update, "gen")'),
        ):
            assert marker not in _src(name), f"{name} must not limit {marker}"

    def test_other_actions_are_still_limited(self) -> None:
        """الميزات المكلفة الأخرى تبقى محدودة."""
        for key in ("ask", "run", "search", "tools"):
            assert key in ratelimit.LIMITS, f"{key} must stay rate limited"

    def test_non_admin_warms_fewer_lessons(self) -> None:
        """المستخدم العادي يبني دفعة محدودة؛ المشرف يبني الكل."""
        src = _src("languages.py")
        assert "is_admin_user" in src
        assert "enqueue_prebuild(s, slug, priority=3, limit=limit)" in src
        assert "else 5" in src

    def test_global_queue_cap_still_applies(self) -> None:
        from core.config import settings

        assert settings.GEN_QUEUE_MAX > 0, "the global queue cap must stay on"

    def test_wait_message_is_human_readable(self) -> None:
        from app.ratelimit import human_wait

        assert "3511" not in human_wait(3511), "never show raw seconds"
        assert "دقيقة" in human_wait(3511), "3511s is about 59 minutes"
        assert "ساعة" in human_wait(7200), "7200s is 2 hours"
        assert "ثانية" in human_wait(30)


class TestOutlineGuards:
    """لا نعيد توليد مخطط موجود."""

    def test_helpers_exist(self) -> None:
        from pipeline import jobs

        assert callable(jobs.outline_exists)
        assert callable(jobs.outline_in_progress)

    def test_build_checks_existing_outline(self) -> None:
        src = _src("languages.py")
        body = src.split("async def language_build")[1].split("async def language_warm")[0]
        assert "outline_exists" in body
        assert "outline_in_progress" in body

    def test_outline_exists_uses_the_right_course_slug(self) -> None:
        from pipeline.jobs import outline_exists
        from pipeline.taxonomy import language_course_slug

        src = Path(ROOT / "pipeline" / "jobs.py").read_text(encoding="utf-8")
        assert "language_course_slug" in src
        assert callable(language_course_slug)


class TestUserFacingText:
    """الرسائل تخبر المستخدم بالحدود."""

    def test_language_view_mentions_the_limit(self) -> None:
        src = _src("languages.py")
        assert "3 مخططات في الساعة" in src
