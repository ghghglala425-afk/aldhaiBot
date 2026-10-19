# -*- coding: utf-8 -*-
"""اختبارات منسّق الدروس الاحترافي."""
from __future__ import annotations

from app import lesson_view as lv


class TestEscaping:
    def test_escapes_html(self) -> None:
        assert lv.esc("<b>x</b>") == "&lt;b&gt;x&lt;/b&gt;"
        assert lv.esc("a & b") == "a &amp; b"

    def test_escapes_none(self) -> None:
        assert lv.esc("") == ""
        assert lv.esc(None) == ""


class TestMarkdownToTelegram:
    def test_bold_and_italic(self) -> None:
        out = lv.md_to_tg("**عريض** و *مائل*")
        assert "<b>عريض</b>" in out
        assert "<i>مائل</i>" in out

    def test_inline_code(self) -> None:
        assert "<code>x=1</code>" in lv.md_to_tg("`x=1`")

    def test_headings(self) -> None:
        out = lv.md_to_tg("## عنوان\nنص")
        assert "<u>عنوان</u>" in out

    def test_bullets(self) -> None:
        out = lv.md_to_tg("- أول\n- ثان")
        assert out.count("▫️") == 2

    def test_numbered(self) -> None:
        out = lv.md_to_tg("1. أول\n2. ثان")
        assert "1️⃣" in out
        assert "2️⃣" in out

    def test_divider(self) -> None:
        assert lv.SEP in lv.md_to_tg("---")

    def test_html_is_escaped_first(self) -> None:
        out = lv.md_to_tg("<script>alert(1)</script>")
        assert "<script>" not in out
        assert "&lt;script&gt;" in out


class TestSplitSections:
    def test_splits_by_headings(self) -> None:
        md = "## أول\nنص أ\n## ثان\nنص ب"
        sections = lv.split_markdown_sections(md)
        assert "أول" in sections
        assert "ثان" in sections
        assert "نص أ" in sections["أول"]

    def test_empty_input(self) -> None:
        assert lv.split_markdown_sections("") == {}


class TestHeader:
    def test_contains_title_and_progress(self) -> None:
        out = lv.render_header(
            "عنوان", "ملخص", difficulty="advanced", est_minutes=30,
            lesson_number=3, total_lessons=10, progress_percent=30,
        )
        assert "عنوان" in out
        assert "3/10" in out
        assert "30%" in out
        assert "متقدم" in out
        assert "🔴" in out
        assert "🟩" in out

    def test_progress_bar_length(self) -> None:
        bar = lv._bar(50, width=10)
        assert bar.count("🟩") == 5
        assert bar.count("⬜") == 5

    def test_progress_bar_clamped(self) -> None:
        assert lv._bar(999, width=10).count("🟩") == 10
        assert lv._bar(-5, width=10).count("🟩") == 0


class TestObjectives:
    def test_numbered_list(self) -> None:
        out = lv.render_objectives(["أ", "ب"])
        assert "1️⃣" in out
        assert "2️⃣" in out
        assert "ماذا ستتعلّم" in out

    def test_empty(self) -> None:
        assert lv.render_objectives([]) == ""
        assert lv.render_objectives(None) == ""


class TestKeyPointsAndHook:
    def test_key_points(self) -> None:
        out = lv.render_key_points(["أ", "ب"])
        assert "نقاط المفتاح" in out
        assert out.count("🟢") == 2

    def test_memory_hook(self) -> None:
        out = lv.render_memory_hook("احفظني")
        assert "احفظ" in out
        assert "احفظني" in out

    def test_empty_hook(self) -> None:
        assert lv.render_memory_hook("") == ""


class TestWarnings:
    def test_gotchas_and_security(self) -> None:
        out = lv.render_warnings(["خطأ شائع"], ["خطر أمني"])
        assert "أخطاء شائعة" in out
        assert "تنبيه أمني" in out
        assert "❌" in out
        assert "🔴" in out

    def test_empty(self) -> None:
        assert lv.render_warnings([], []) == ""


class TestCodeBlock:
    def test_code_is_escaped_and_labelled(self) -> None:
        out = lv.render_code_block("print('<x>')", "python", 2, 5, "مثال")
        assert "&lt;x&gt;" in out
        assert "<pre>" in out
        assert "2/5" in out
        assert "مثال" in out
        assert "python" in out


class TestReviewCard:
    def test_contains_all_parts(self) -> None:
        out = lv.render_review_card(
            summary="ملخص", key_points=["نقطة"], memory_hook="خطاف", next_step="التالي"
        )
        assert "بطاقة المراجعة" in out
        assert "ملخص" in out
        assert "نقطة" in out
        assert "خطاف" in out
        assert "التالي" in out


class TestFlashcard:
    def test_front_only(self) -> None:
        out = lv.render_flashcard(
            {"front": "س؟", "options": ["أ", "ب"], "back": "إجابة"}, 1, 3, revealed=False
        )
        assert "س؟" in out
        assert "اكشف" in out
        # لا يظهر الجواب قبل الكشف
        assert "إجابة" not in out

    def test_revealed_shows_answer(self) -> None:
        out = lv.render_flashcard(
            {"front": "س؟", "options": ["أ"], "back": "إجابة", "explanation": "شرح"}, 1, 3, revealed=True
        )
        assert "إجابة" in out
        assert "شرح" in out


class TestSection:
    def test_section(self) -> None:
        out = lv.render_section("عنوان", "نص")
        assert "عنوان" in out
        assert "نص" in out

    def test_empty_section(self) -> None:
        assert lv.render_section("عنوان", "") == ""
