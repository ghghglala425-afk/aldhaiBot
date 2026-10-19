# -*- coding: utf-8 -*-
"""اختبار بوابة التحقق (بدون تنفيذ وبدون قاعدة بيانات)."""
import asyncio

from core.config import settings
from pipeline.schema import GeneratedLesson
from pipeline.verifier import verify_lesson


def _usage(j: int) -> dict:
    return {
        "name": f"استخدام {j}",
        "signature": "f(x)",
        "description": "وصف الاستخدام",
        "example": f"print({j})",
        "output": str(j),
    }


def _code(i: int, usages: int = 0) -> dict:
    c = {
        "language": "python",
        "title": f"مثال {i}",
        "code": f"print({i})",
        "explanation": "طباعة قيمة",
        "expected_output": str(i),
    }
    if usages:
        c["usages"] = [_usage(j) for j in range(usages)]
    return c


def _lesson(n_codes: int, n_q: int = 8, usages: int = 0) -> GeneratedLesson:
    codes = [_code(i, usages) for i in range(n_codes)]
    qs = [
        {"text": f"سؤال رقم {i}", "kind": "single",
         "options": [{"text": "أ", "correct": i % 2 == 0}, {"text": "ب", "correct": i % 2 == 1}],
         "explanation": "شرح"}
        for i in range(n_q)
    ]
    return GeneratedLesson(
        title="درس اختباري كامل", summary="ملخص كافٍ للدرس", objectives=["هدف أول", "هدف ثانٍ"],
        content_md="ن" * 260, code_samples=codes, quiz_questions=qs,
    )


def test_verifier_passes_valid_lesson_without_exec():
    rep = asyncio.run(verify_lesson(_lesson(settings.GEN_MIN_CODES, n_q=settings.GEN_MIN_CODES * 2), expect_language="python",
                                    check_exec=False, check_atlas=False))
    assert rep.passed, rep.issues


def test_verifier_fails_few_codes():
    rep = asyncio.run(verify_lesson(_lesson(settings.GEN_MIN_CODES - 1), expect_language="python",
                                    check_exec=False, check_atlas=False))
    assert not rep.passed


def test_verifier_fails_few_questions():
    rep = asyncio.run(verify_lesson(_lesson(settings.GEN_MIN_CODES, n_q=settings.GEN_MIN_CODES * 2 - 1), expect_language="python",
                                    check_exec=False, check_atlas=False))
    assert not rep.passed


def test_verifier_atlas_passes_when_sufficient():
    rep = asyncio.run(verify_lesson(_lesson(settings.GEN_MIN_CODES, usages=settings.GEN_MIN_USAGES, n_q=settings.GEN_MIN_CODES * 2), expect_language="python", check_exec=False, check_atlas=True))
    assert rep.passed, rep.issues


def test_verifier_atlas_fails_when_missing_usages():
    rep = asyncio.run(verify_lesson(_lesson(settings.GEN_MIN_CODES, usages=2), expect_language="python",
                                    check_exec=False, check_atlas=True))
    assert not rep.passed
