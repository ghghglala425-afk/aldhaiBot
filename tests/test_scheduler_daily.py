# -*- coding: utf-8 -*-
"""يومية الدرس اليومي: لا تُستخدم جلسة قاعدة البيانات بعد إغلاقها (تسرّب اتصالات)."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app import scheduler


class _FakeResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return self

    def all(self):
        return self._items


class _FakeSession:
    def __init__(self, ids):
        self.ids = ids
        self.closed = False
        self.used_after_close = False

    async def __aenter__(self):
        # الجلسة نفسها تُعاد للاستخدام في كل كتلة، فإعادة الفتح تُصفّر الحالة.
        self.closed = False
        return self

    async def __aexit__(self, *exc):
        self.closed = True
        return False

    async def execute(self, *args, **kwargs):
        return _FakeResult(self.ids)

    async def get(self, *args, **kwargs):
        if self.closed:
            self.used_after_close = True
        return object()


class _FakeBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, chat_id, text, **kwargs):
        self.messages.append((chat_id, text, kwargs))


def test_send_daily_keeps_session_open_until_lesson_day(monkeypatch):
    session = _FakeSession([777])
    bot = _FakeBot()
    lesson = SimpleNamespace(id=42, title="درس اليوم التجريبي", summary="ملخص")
    seen_closed: list[bool] = []

    monkeypatch.setattr(scheduler, "SessionLocal", lambda: session)

    async def fake_user(s, tg_id):
        return SimpleNamespace(id=1, telegram_id=tg_id)

    async def fake_today(s, user):
        return lesson

    async def fake_day(s, item):
        seen_closed.append(s.closed)
        return 3

    monkeypatch.setattr(scheduler, "get_user_by_telegram", fake_user)
    monkeypatch.setattr(scheduler, "todays_daily", fake_today)
    monkeypatch.setattr(scheduler, "lesson_day", fake_day)

    asyncio.run(scheduler._send_daily(SimpleNamespace(bot=bot)))

    assert seen_closed == [False], "استُخدمت الجلسة بعد إغلاقها"
    assert session.used_after_close is False
    assert len(bot.messages) == 1
    chat_id, text, kwargs = bot.messages[0]
    assert chat_id == 777
    assert "درس اليوم التجريبي" in text
    assert kwargs["reply_markup"] is not None
