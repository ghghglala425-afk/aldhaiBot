# -*- coding: utf-8 -*-
"""صلابة التوليد: تطبيع المخطط، توزيع الإجابات، وإصلاح/عزل الأكواد الفاشلة."""
from __future__ import annotations

import asyncio

from core.config import settings
from pipeline import generator, verifier
from pipeline.code_repair import repair_code
from pipeline.quality import balance_quiz
from pipeline.sandbox_runner import RunResult
from pipeline.schema import GeneratedLesson
from pipeline.verifier import (
    VerifyReport,
    drop_failed_codes,
    only_exec_failures,
    verify_lesson,
)


def _lesson_payload(n_codes: int, n_q: int, *, language: str = "python") -> dict:
    return {
        "title": "درس اختباري كامل",
        "summary": "ملخص كافٍ للتحقق من المسار المولّد",
        "objectives": ["هدف أول", "هدف ثانٍ"],
        "content_md": "ن" * 260,
        "difficulty": "beginner",
        "code_samples": [
            {
                "language": language,
                "title": f"مثال {i}",
                "code": f"print({i})",
                "explanation": "طباعة قيمة رقمية",
                "expected_output": str(i),
            }
            for i in range(n_codes)
        ],
        "quiz_questions": [
            {
                "text": f"سؤال رقم {i}",
                "kind": "single",
                "options": [
                    {"text": "أ", "correct": i % 2 == 0},
                    {"text": "ب", "correct": i % 2 == 1},
                ],
                "explanation": "شرح الإجابة",
            }
            for i in range(n_q)
        ],
    }


def _ok(stdout: str = "1") -> RunResult:
    return RunResult("ok", "judge0", stdout=stdout)


def _fail(detail: str = "Judge0: Compilation Error") -> RunResult:
    return RunResult("error", "judge0", detail=detail)


# ---------------------------------------------------------------------
#  تطبيع مخرجات النماذج (JSON متسامح)
# ---------------------------------------------------------------------
def test_schema_accepts_plain_string_options_and_correct_index():
    lesson = GeneratedLesson.model_validate(
        {
            "title": "درس تطبيع الخيارات",
            "summary": "ملخص كافٍ لدرس التطبيع",
            "objectives": ["هدف أول", "هدف ثانٍ"],
            "content_md": "ن" * 260,
            "code_samples": [
                {
                    "lang": "c++",
                    "title": "طباعة",
                    "example": '#include <iostream>\nint main(){ std::cout << 1; }',
                    "explanation": "طباعة قيمة",
                }
            ],
            "questions": [
                {
                    "question": "ما ناتج الكود؟",
                    "type": "single_choice",
                    "options": ["1", "2", "3"],
                    "correct_index": 1,
                    "explanation": "لأن الكود يطبع 2",
                }
            ],
        }
    )
    question = lesson.quiz_questions[0]
    assert [o.correct for o in question.options] == [False, True, False]
    assert question.kind == "single"
    assert lesson.code_samples[0].language == "cpp"
    assert "std::cout" in lesson.code_samples[0].code


def test_schema_accepts_mapping_options_with_letter_answer():
    question = GeneratedLesson.model_validate(
        {
            **_lesson_payload(1, 1),
            "quiz_questions": [
                {
                    "text": "اختر الإجابة الصحيحة",
                    "options": {"A": "أول", "B": "ثاني", "C": "ثالث"},
                    "answer": "B",
                }
            ],
        }
    ).quiz_questions[0]
    assert [o.correct for o in question.options] == [False, True, False]
    assert [o.text for o in question.options] == ["أول", "ثاني", "ثالث"]


def test_schema_accepts_is_correct_alias_and_language_aliases():
    lesson = GeneratedLesson.model_validate(
        {
            **_lesson_payload(1, 1),
            "code_samples": [
                {
                    "language": "js",
                    "title": "طباعة",
                    "code": "console.log(1);",
                    "explanation": "طباعة في الطرفية",
                }
            ],
            "quiz_questions": [
                {
                    "text": "اختر الإجابة الصحيحة",
                    "options": [
                        {"option": "أ", "is_correct": 1},
                        {"option": "ب", "is_correct": 0},
                    ],
                }
            ],
        }
    )
    assert lesson.code_samples[0].language == "javascript"
    assert [o.correct for o in lesson.quiz_questions[0].options] == [True, False]


# ---------------------------------------------------------------------
#  توزيع الإجابات الصحيحة
# ---------------------------------------------------------------------
def test_balance_quiz_distributes_positions_and_fixes_multi_correct():
    payload = _lesson_payload(2, 4)
    for question in payload["quiz_questions"]:
        for option in question["options"]:
            option["correct"] = False
        question["options"][0]["correct"] = True
    payload["quiz_questions"][1]["options"][1]["correct"] = True  # أكثر من صحيحة

    lesson = GeneratedLesson.model_validate(payload)
    changed = balance_quiz(lesson)

    assert changed > 0
    positions = [
        next(i for i, o in enumerate(q.options) if o.correct)
        for q in lesson.quiz_questions
    ]
    assert len(set(positions)) > 1, "ما زالت كل الإجابات في الموضع نفسه"
    for question in lesson.quiz_questions:
        assert sum(o.correct for o in question.options) == 1


# ---------------------------------------------------------------------
#  إصلاح الأكواد
# ---------------------------------------------------------------------
def test_repair_code_adds_cpp_headers_and_std_namespace():
    fixed = repair_code("cpp", "int main(){ cout << 1; return 0; }")
    assert "#include <iostream>" in fixed
    assert "using namespace std;" in fixed
    assert fixed.index("#include") < fixed.index("using namespace std;")


def test_repair_code_keeps_valid_includes_and_strips_fences():
    fixed = repair_code("cpp", "```cpp\n#include <iostream>\nint main(){ cout << 1; }\n```")
    assert fixed.count("#include") == 1
    assert "```" not in fixed
    assert "using namespace std;" in fixed


def test_repair_code_renames_java_public_class():
    fixed = repair_code(
        "java",
        "public class Demo { public static void main(String[] a){ System.out.println(1); } }",
    )
    assert "public class Main" in fixed
    assert "Demo" not in fixed


# ---------------------------------------------------------------------
#  عزل الأكواد الفاشلة بعد إصلاحها
# ---------------------------------------------------------------------
def test_verifier_repairs_failing_code_and_keeps_it(monkeypatch):
    async def fake_run(language, code, **kwargs):
        if language == "cpp" and "#include" not in code:
            return _fail()
        return _ok()

    monkeypatch.setattr(verifier, "run_code", fake_run)

    lesson = GeneratedLesson.model_validate(
        {
            **_lesson_payload(1, 2),
            "code_samples": [
                {
                    "language": "c++",
                    "title": "طباعة",
                    "code": "int main(){ cout << 1; return 0; }",
                    "explanation": "طباعة رقم في الطرفية",
                    "expected_output": "1",
                }
            ],
        }
    )
    report = asyncio.run(
        verify_lesson(
            lesson, expect_language="cpp", check_exec=True, check_atlas=False, min_codes=1
        )
    )

    assert report.passed, report.issues
    assert report.exec_ok == 1
    assert "#include <iostream>" in lesson.code_samples[0].code
    assert any("أُصلح تلقائياً" in note for note in report.notes)


def test_verifier_reports_and_drops_failed_codes(monkeypatch):
    async def fake_run(language, code, **kwargs):
        return _fail() if "print(1)" in code else _ok()

    monkeypatch.setattr(verifier, "run_code", fake_run)

    n = settings.GEN_MIN_CODES
    lesson = GeneratedLesson.model_validate(_lesson_payload(n, n * 2))
    report = asyncio.run(
        verify_lesson(lesson, expect_language="python", check_exec=True, check_atlas=False)
    )

    assert not report.passed
    assert report.failed_code_indices == [2]
    assert only_exec_failures(report)
    assert drop_failed_codes(lesson, report)
    assert len(lesson.code_samples) == n - 1

    rescue = asyncio.run(
        verify_lesson(
            lesson,
            expect_language="python",
            check_exec=False,
            check_atlas=False,
            min_codes=len(lesson.code_samples),
        )
    )
    assert rescue.passed, rescue.issues


def test_drop_failed_codes_refuses_when_no_code_survives():
    lesson = GeneratedLesson.model_validate(_lesson_payload(1, 2))
    report = VerifyReport(passed=False)
    report.failed_code_indices = [1]
    assert not drop_failed_codes(lesson, report)
    assert len(lesson.code_samples) == 1


def test_only_exec_failures_ignores_other_issues():
    report = VerifyReport(passed=False)
    report.issues = ["عدد الأكواد قليل", "كود1 فشل التنفيذ: خطأ"]
    report.exec_issues = ["كود1 فشل التنفيذ: خطأ"]
    assert not only_exec_failures(report)


# ---------------------------------------------------------------------
#  حلقة التوليد: أخطاء المخطط واستدعاء AI الإضافي
# ---------------------------------------------------------------------
def test_generator_retries_on_validation_error(monkeypatch):
    calls: list[str] = []
    valid = _lesson_payload(settings.GEN_FAST_CODES, settings.GEN_FAST_CODES * 2)

    async def fake_chat(system, user, **kwargs):
        calls.append(user)
        if len(calls) == 1:
            return {"title": "ناقص", "quiz_questions": [{"options": [["سيئ"]]}]}
        return valid

    monkeypatch.setattr(generator, "chat_json", fake_chat)
    monkeypatch.setattr(settings, "VERIFY_EXEC", False)

    lesson, report = asyncio.run(
        generator.generate_lesson("المتغيرات", "python", fast=True)
    )

    assert report.passed, report.issues
    assert len(calls) == 2
    assert "JSON" in calls[1]
    assert "summary" in calls[1]
    assert lesson.title == valid["title"]


def test_generator_rescues_lesson_by_dropping_failed_code(monkeypatch):
    calls: list[str] = []

    async def fake_chat(system, user, **kwargs):
        calls.append(user)
        return _lesson_payload(settings.GEN_FAST_CODES, settings.GEN_FAST_CODES * 2)

    async def fake_run(language, code, **kwargs):
        return _fail() if "print(1)" in code else _ok()

    monkeypatch.setattr(generator, "chat_json", fake_chat)
    monkeypatch.setattr(verifier, "run_code", fake_run)
    monkeypatch.setattr(settings, "VERIFY_EXEC", True)
    monkeypatch.setattr(settings, "GEN_ENRICH_ATLAS", False)

    lesson, report = asyncio.run(
        generator.generate_lesson("المتغيرات", "python", fast=True)
    )

    assert report.passed, report.issues
    assert len(calls) == 1, "كان يجب الإنقاذ بلا استدعاء AI إضافي"
    assert len(lesson.code_samples) == settings.GEN_FAST_CODES - 1
    assert not any("print(1)" in c.code for c in lesson.code_samples)
