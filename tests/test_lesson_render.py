# -*- coding: utf-8 -*-
"""اختبارات تجميع نصوص الدرس وتقسيم الرسائل الطويلة."""
from __future__ import annotations

import asyncio

from app.handlers import learn


class _FakeMessage:
    def __init__(self) -> None:
        self.parts: list[str] = []

    async def reply_text(self, text: str, **kwargs) -> None:
        self.parts.append(text)


def test_flush_blocks_empty() -> None:
    msg = _FakeMessage()
    blocks: list[str] = []
    asyncio.run(learn._flush_blocks(msg, blocks))
    assert msg.parts == []


def test_flush_blocks_joins_and_clears() -> None:
    msg = _FakeMessage()
    blocks = ["a", "b", "c"]
    asyncio.run(learn._flush_blocks(msg, blocks))
    assert msg.parts == ["a\n\nb\n\nc"]
    assert blocks == []


def test_chunks_split_long_text_without_loss() -> None:
    msg = _FakeMessage()
    text = "\n".join(f"line {i} " + "x" * 80 for i in range(200))
    asyncio.run(learn._send_html_chunks(msg, text))
    assert len(msg.parts) > 1
    assert all(len(part) <= 4000 for part in msg.parts)
    assert "".join(msg.parts).replace("\n", "") == text.replace("\n", "")


def test_single_huge_line_is_not_truncated() -> None:
    msg = _FakeMessage()
    text = "<b>" + "x" * 5000 + "</b>"
    asyncio.run(learn._send_html_chunks(msg, text))
    assert "".join(msg.parts) == text
    assert all(len(part) <= 4000 for part in msg.parts)
