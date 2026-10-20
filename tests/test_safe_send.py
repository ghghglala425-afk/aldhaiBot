# -*- coding: utf-8 -*-
"""اختبارات: عناوين المولَّدة بـ AI لا تُعطّل القوائم.

المشكلة: عنوان مثل «الدرس الأول: أساسيات_الأمن» يحتوي `_` فيكسر تحليل
Markdown فيرمي Telegram `BadRequest: can't parse entities` ويظهر للمستخدم
«⚠️ حدث خطأ غير متوقع».
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest


class TestSafeSend:
    """الإرسال الآمن يعيد المحاولة كنص عادي."""

    def test_escape_md_escapes_specials(self) -> None:
        from app.tg import escape_md

        out = escape_md("أساسيات_الأمن *ومرور* `code` [x]")
        assert "\\_" in out
        assert "\\*" in out
        assert "\\`" in out
        assert "\\[" in out

    def test_escape_md_handles_empty(self) -> None:
        from app.tg import escape_md

        assert escape_md(None) == ""
        assert escape_md("") == ""

    def test_send_falls_back_to_plain_text(self) -> None:
        """عند فشل التحليل تُرسل الرسالة نصا عاديا."""
        from telegram.error import BadRequest

        from app.tg import send_text

        calls: list[dict] = []

        async def fake_reply(text, **kwargs):
            calls.append(kwargs)
            if kwargs.get("parse_mode") is not None:
                raise BadRequest("Can't parse entities: unsupported start tag")
            return Mock()

        msg = Mock()
        msg.reply_text = fake_reply

        ok = asyncio.run(send_text(msg, "عنوان فيه _ و *", parse_mode="Markdown"))
        assert ok is True
        assert len(calls) == 2, "the first attempt must fail and the second succeed"
        assert calls[0]["parse_mode"] is not None
        assert calls[1]["parse_mode"] is None

    def test_send_succeeds_first_time(self) -> None:
        from app.tg import send_text

        calls: list[dict] = []

        async def fake_reply(text, **kwargs):
            calls.append(kwargs)
            return Mock()

        msg = Mock()
        msg.reply_text = fake_reply

        ok = asyncio.run(send_text(msg, "نص", parse_mode="Markdown"))
        assert ok is True
        assert len(calls) == 1

    def test_other_bad_requests_are_not_swallowed(self) -> None:
        """خطأ غير متعلق بالتحليل يجب أن يبقى يرتفع."""
        from telegram.error import BadRequest

        from app.tg import send_text

        async def fake_reply(text, **kwargs):
            raise BadRequest("chat not found")

        msg = Mock()
        msg.reply_text = fake_reply

        with pytest.raises(BadRequest):
            asyncio.run(send_text(msg, "نص", parse_mode="Markdown"))

    def test_edit_text_is_safe(self) -> None:
        from telegram.error import BadRequest

        from app.tg import edit_text

        calls: list[dict] = []

        async def fake_edit(text, **kwargs):
            calls.append(kwargs)
            if kwargs.get("parse_mode") is not None:
                raise BadRequest("can't parse entities")
            return Mock()

        q = Mock()
        q.edit_message_text = fake_edit

        ok = asyncio.run(edit_text(q, "عنوان _problem_", parse_mode="Markdown"))
        assert ok is True
        assert len(calls) == 2

    def test_answer_never_raises(self) -> None:
        from app.tg import answer

        async def fake_answer(text, **kwargs):
            raise RuntimeError("query is too old")

        q = Mock()
        q.answer = fake_answer
        assert asyncio.run(answer(q, "نص")) is False


class TestHandlersUseSafeSend:
    """كل قائمة فيها محتوى مولَّد يجب أن تمرّ عبر الإرسال الآمن."""

    def _src(self, name: str) -> str:
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        return (root / "app" / "handlers" / name).read_text(encoding="utf-8")

    @pytest.mark.parametrize(
        "name",
        ["learn.py", "languages.py", "profile.py", "qa.py", "search.py", "labs.py"],
    )
    def test_handler_uses_tg(self, name: str) -> None:
        assert "from app import tg" in self._src(name), f"{name} must import the safe sender"

    @pytest.mark.parametrize(
        "name",
        ["learn.py", "languages.py", "profile.py", "qa.py", "search.py", "labs.py"],
    )
    def test_no_raw_edit_message_text(self, name: str) -> None:
        src = self._src(name)
        assert "await q.edit_message_text(" not in src, (
            f"{name} still sends raw edit_message_text"
        )

    def test_course_list_uses_safe_edit(self) -> None:
        src = self._src("learn.py")
        assert "tg.edit_text(q" in src


class TestDynamicContentIsEscaped:
    """العناوين المولَّدة يجب أن تُهرَّب قبل إدراجها في Markdown."""

    def test_course_list_escapes_titles(self) -> None:
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        src = (root / "app" / "handlers" / "learn.py").read_text(encoding="utf-8")
        assert "tg.escape_md(course.title)" in src
        assert "tg.escape_md(st_title)" in src
        assert "tg.escape_md(lsn.title)" in src

    def test_language_list_escapes_titles(self) -> None:
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        src = (root / "app" / "handlers" / "languages.py").read_text(encoding="utf-8")
        assert "tg.escape_md(l.title)" in src
        assert "tg.escape_md(name_ar)" in src

    def test_html_renderers_escape(self) -> None:
        """مُنسّق الدرس يعمل بـ HTML — كل نص ديناميكي يُهرَّب."""
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        src = (root / "app" / "lesson_view.py").read_text(encoding="utf-8")
        assert "esc(o)" in src, "objectives must be escaped"
        assert "esc(text)" in src, "bullet items must be escaped"
        assert "esc(card.get('back', ''))" in src


class TestRateLimitsRemovedForGeneration:
    """التوليد بلا حدود زمنية (حسب طلب المستخدم)."""

    def test_generation_keys_have_no_limit(self) -> None:
        from app import ratelimit

        for key in ("outline", "warm", "gen"):
            assert key not in ratelimit.LIMITS, f"{key} must not be rate limited"

    def test_handlers_do_not_guard_generation(self) -> None:
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        for name in ("languages.py", "learn.py"):
            src = (root / "app" / "handlers" / name).read_text(encoding="utf-8")
            assert 'ratelimit.guard(update, "outline")' not in src
            assert 'ratelimit.guard(update, "warm")' not in src
            assert 'ratelimit.guard(update, "gen")' not in src

    def test_human_wait_is_readable(self) -> None:
        from app.ratelimit import human_wait

        assert "لحظات" in human_wait(0)
        assert "ثانية" in human_wait(30)
        assert "دقيقة" in human_wait(300)
        assert "ساعة" in human_wait(4000)
