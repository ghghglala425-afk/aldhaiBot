# -*- coding: utf-8 -*-
"""اختبارات ربط البوت: كل زر/أمر له معالج، وبناء التطبيق ينجح بمجموعاته."""
from __future__ import annotations

import pathlib
import re

from app import keyboards as kb
from core.config import settings

ROOT = pathlib.Path(__file__).resolve().parents[1]
HANDLERS = ROOT / "app" / "handlers"

CALLBACK_RE = re.compile(r'callback_data=(?:f)?["\']([a-z_]+):')
PATTERN_RE = re.compile(r'pattern=r?["\']\^([a-z_]+)')


def _sources() -> list[tuple[str, str]]:
    files = list(HANDLERS.glob("*.py")) + [ROOT / "app" / "keyboards.py", ROOT / "app" / "pagination.py"]
    return [(f.name, f.read_text(encoding="utf-8")) for f in files]


def test_every_callback_prefix_has_a_handler():
    prefixes: set[str] = set()
    patterns: set[str] = set()
    for _, text in _sources():
        prefixes |= set(CALLBACK_RE.findall(text))
        patterns |= set(PATTERN_RE.findall(text))
    missing = sorted(p for p in prefixes if p not in patterns)
    assert not missing, f"callbacks بلا معالج: {missing}"


def test_immediate_menu_buttons_are_wired():
    from app.handlers import menu

    expected = {
        kb.MENU_COURSES, kb.MENU_LANGUAGES, kb.MENU_PATHS,
        kb.MENU_DAILY, kb.MENU_RANK, kb.MENU_ACCOUNT,
    }
    assert set(menu.IMMEDIATE) == expected


def test_interactive_menu_buttons_have_conversation_entries():
    mapping = {
        kb.MENU_ASSISTANT: "assistant.py",
        kb.MENU_SEARCH: "search.py",
        kb.MENU_RUN: "runner.py",
        kb.MENU_TOOLS: "tools.py",
    }
    for text, fname in mapping.items():
        src = (HANDLERS / fname).read_text(encoding="utf-8")
        assert text in src, f"الزر «{text}» غير مربوط في {fname}"


def test_all_menu_texts_are_unique_and_covered():
    assert len(kb.MENU_TEXTS) == len(set(kb.MENU_TEXTS))
    assert len(kb.MENU_TEXTS) == 10


def test_application_builds_with_groups_0_to_9():
    from app.bot import build_application

    saved = settings.BOT_TOKEN
    settings.BOT_TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"
    try:
        app = build_application()
    finally:
        settings.BOT_TOKEN = saved
    groups = set(app.handlers.keys())
    assert set(range(0, 10)).issubset(groups), f"مجموعات ناقصة: {sorted(groups)}"


def test_commands_are_unique():
    from app.bot import COMMANDS

    names = [c.command for c in COMMANDS]
    assert len(names) == len(set(names)), "أوامر مكرّرة في القائمة"
    for required in {"start", "courses", "languages", "paths", "search", "ask", "run", "tools", "export"}:
        assert required in names
