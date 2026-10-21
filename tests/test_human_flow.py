# -*- coding: utf-8 -*-
"""محاكاة استخدام بشري لمسارات البوت الرئيسية (بلا شبكة ولا تلجرام حقيقي)."""
from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import func, select

from app.handlers import languages as languages_handler
from app.handlers import learn as learn_handler
from app.handlers import exercise as exercise_handler
from core.config import settings
from core.db import SessionLocal, init_db
from core.models import Course, Lesson, Stage, User
from core.repo import create_user
from pipeline import seed
from pipeline.taxonomy import language_course_slug


class FakeMessage:
    def __init__(self, chat_id: int = 4242, text: str = ""):
        self.chat_id = chat_id
        self.text = text
        self.reply_text = AsyncMock(side_effect=lambda *a, **k: FakeMessage(chat_id))
        self.edit_text = AsyncMock()
        self.delete = AsyncMock()


class FakeQuery:
    def __init__(self, data: str, message: FakeMessage):
        self.data = data
        self.message = message
        self.answer = AsyncMock()
        self.edit_message_reply_markup = AsyncMock()


def _update(data: str, user_id: int, chat_id: int = 4242):
    msg = FakeMessage(chat_id)
    return SimpleNamespace(
        callback_query=FakeQuery(data, msg),
        effective_message=msg,
        effective_chat=SimpleNamespace(id=chat_id),
        effective_user=SimpleNamespace(id=user_id),
    )


def _context():
    return SimpleNamespace(
        bot=SimpleNamespace(send_message=AsyncMock(side_effect=lambda *a, **k: FakeMessage())),
        user_data={},
    )


def _markups(call_args_list):
    data = set()
    for call in call_args_list:
        markup = call.kwargs.get("reply_markup")
        for row in getattr(markup, "inline_keyboard", []) or []:
            for btn in row:
                if getattr(btn, "callback_data", None):
                    data.add(btn.callback_data)
    return data


async def _prepare() -> None:
    await init_db()
    await seed.seed_languages()
    async with SessionLocal() as s:
        has_demo = await s.scalar(select(Lesson).where(Lesson.slug == "hello-security"))
    if not has_demo:
        await seed.seed_demo_course()


async def _new_user() -> int:
    tg_id = 700_000_000 + uuid.uuid4().int % 100_000_000
    async with SessionLocal() as s:
        await create_user(s, telegram_id=tg_id, username=f"u{tg_id}")
    return tg_id


def test_language_open_builds_200_lessons_without_ai():
    asyncio.run(_prepare())
    update = _update("lang:rust", user_id=1)
    ctx = _context()
    send = AsyncMock()
    edit = AsyncMock()
    with (
        patch.object(settings, "GEN_PREBUILD_ON_OPEN", False),
        patch("app.tg.edit_text", edit),
        patch("app.tg.send_text", send),
    ):
        asyncio.run(languages_handler.language_open(update, ctx))

    assert edit.await_count == 1
    text = edit.await_args.args[1]
    assert "إتقان" in text
    markup = edit.await_args.kwargs.get("reply_markup")
    callbacks = {
        btn.callback_data
        for row in markup.inline_keyboard
        for btn in row
        if btn.callback_data
    }
    assert "langst:rust:1:0" in callbacks
    assert "langs:0" in callbacks

    async def _check():
        async with SessionLocal() as s:
            course = await s.scalar(
                select(Course).where(Course.slug == language_course_slug("rust"))
            )
            assert course is not None
            stages = list(
                (await s.execute(select(Stage).where(Stage.course_id == course.id))).scalars().all()
            )
            assert len(stages) == 10
            n = await s.scalar(
                select(func.count(Lesson.id))
                .join(Stage, Stage.id == Lesson.stage_id)
                .where(Stage.course_id == course.id)
            )
            assert n == 200

    asyncio.run(_check())


def test_stage_lessons_lists_outline_lessons():
    asyncio.run(_prepare())
    update = _update("langst:rust:1:0", user_id=1)
    ctx = _context()
    edit = AsyncMock()
    with (
        patch.object(settings, "GEN_PREBUILD_ON_OPEN", False),
        patch("app.tg.edit_text", edit),
    ):
        asyncio.run(languages_handler.stage_lessons(update, ctx))

    assert edit.await_count == 1
    markup = edit.await_args.kwargs.get("reply_markup")
    callbacks = {
        btn.callback_data
        for row in markup.inline_keyboard
        for btn in row
        if btn.callback_data
    }
    assert any(c.startswith("lesson:") for c in callbacks)
    assert "lang:rust" in callbacks


def test_human_flow_lesson_quiz_and_exercise_buttons():
    asyncio.run(_prepare())
    tg_id = asyncio.run(_new_user())

    async def _demo_id() -> int:
        async with SessionLocal() as s:
            return int(await s.scalar(select(Lesson.id).where(Lesson.slug == "hello-security")))

    lesson_id = asyncio.run(_demo_id())
    update = _update(f"lesson:{lesson_id}", user_id=tg_id)
    ctx = _context()
    send = AsyncMock()
    with (
        patch.object(settings, "GEN_LAZY_ON_OPEN", False),
        patch.object(settings, "GEN_PREBUILD_ON_OPEN", False),
        patch("app.handlers.learn._spawn", lambda coro: coro.close()),
        patch("app.tg.send_text", send),
    ):
        asyncio.run(learn_handler.lesson_callback(update, ctx))

    assert send.await_count >= 1
    callbacks = _markups(send.call_args_list)
    assert f"qz_start:{lesson_id}" in callbacks
    assert f"exs:{lesson_id}" in callbacks
    assert f"latt:{lesson_id}" in callbacks

    async def _progress():
        from core.learning import get_progress

        async with SessionLocal() as s:
            user = await s.scalar(select(User).where(User.telegram_id == tg_id))
            return await get_progress(s, user.id, lesson_id)

    assert asyncio.run(_progress()) is not None


def test_exercise_review_mode_when_no_expected_output():
    asyncio.run(_prepare())
    tg_id = asyncio.run(_new_user())

    async def _demo_id() -> int:
        async with SessionLocal() as s:
            return int(await s.scalar(select(Lesson.id).where(Lesson.slug == "hello-security")))

    lesson_id = asyncio.run(_demo_id())
    ctx = _context()
    ctx.user_data["exercise"] = {
        "lesson_id": lesson_id,
        "language": "python",
        "expected": "",
        "ref_code": "print('hi')",
        "ref_title": "test",
        "hint": "",
        "attempts": 0,
        "started": 0,
    }
    update = _update("", user_id=tg_id)
    child = FakeMessage()
    update.message = FakeMessage(text="print('hi')")
    update.message.reply_text = AsyncMock(return_value=child)
    update.effective_message = update.message

    ok = SimpleNamespace(
        status="ok", stdout="hi\n", stderr="", engine="test", detail="", notes=[]
    )
    with patch.object(exercise_handler, "run_code", AsyncMock(return_value=ok)):
        try:
            asyncio.run(exercise_handler.submit_code(update, ctx))
        except Exception as exc:  # ApplicationHandlerStop متوقع
            assert exc.__class__.__name__ == "ApplicationHandlerStop"
    assert "exercise" not in ctx.user_data
    assert "أحسنت" in child.edit_text.await_args.args[0]

    # خرج فارغ = فشل في وضع المراجعة
    ctx.user_data["exercise"] = {
        "lesson_id": lesson_id,
        "language": "python",
        "expected": "",
        "ref_code": "print('hi')",
        "ref_title": "test",
        "hint": "",
        "attempts": 0,
        "started": 0,
    }
    empty = SimpleNamespace(
        status="ok", stdout="", stderr="", engine="test", detail="", notes=[]
    )
    with patch.object(exercise_handler, "run_code", AsyncMock(return_value=empty)):
        try:
            asyncio.run(exercise_handler.submit_code(update, ctx))
        except Exception as exc:  # ApplicationHandlerStop متوقع
            assert exc.__class__.__name__ == "ApplicationHandlerStop"
    assert "ليس بعد" in child.edit_text.await_args.args[0]
