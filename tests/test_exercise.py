# -*- coding: utf-8 -*-
"""اختبارات تمرين الكود المعزول وترقيم الأيام."""
from __future__ import annotations

from app import lesson_view as lv
from app.handlers.exercise import _norm, _strip_fence


class TestCodeNormalization:
    def test_trailing_spaces_and_blank_lines(self) -> None:
        assert _norm("a  \r\nb\n\n") == "a\nb"

    def test_none_is_empty(self) -> None:
        assert _norm(None) == ""

    def test_strip_markdown_fence(self) -> None:
        assert _strip_fence("```python\nprint(1)\n```") == "print(1)"

    def test_plain_code_unchanged(self) -> None:
        assert _strip_fence("print(1)") == "print(1)"


class TestDayNumber:
    def test_header_shows_day(self) -> None:
        out = lv.render_header("عنوان", "ملخص", lesson_number=3, day_number=3)
        assert "اليوم 3" in out

    def test_header_without_day(self) -> None:
        out = lv.render_header("عنوان", "ملخص", lesson_number=3)
        assert "اليوم" not in out


class TestExerciseWiring:
    def test_handlers_registered(self) -> None:
        from app.handlers import exercise

        assert callable(exercise.register_handlers)
        assert callable(exercise.auto_start_after_quiz)

    def test_lessons_expose_attachments_and_exercise(self) -> None:
        from pathlib import Path

        src = (Path(__file__).resolve().parents[1] / "app" / "handlers" / "learn.py").read_text(
            encoding="utf-8"
        )
        assert "latt:" in src
        assert "exs:" in src
        assert "ملحقات الدرس" in src
