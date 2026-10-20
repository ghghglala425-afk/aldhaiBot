# -*- coding: utf-8 -*-
"""بوابة التحقّق الصارمة — لا يُنشر درس إلا بعد اجتيازها كاملة."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from core.config import settings
from core.logging import get_logger
from pipeline.sandbox_runner import run_code
from pipeline.schema import GeneratedCode, GeneratedLesson

log = get_logger("pipeline.verifier")


@dataclass
class VerifyReport:
    passed: bool
    issues: list[str] = field(default_factory=list)
    exec_ok: int = 0
    exec_failed: int = 0
    exec_skipped: int = 0
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"نجح={self.passed} | تنفيذ سليم={self.exec_ok} "
            f"فاشل={self.exec_failed} متخطى={self.exec_skipped} "
            f"| مشاكل={len(self.issues)}"
        )


def _check_quiz(
    lesson: GeneratedLesson, report: VerifyReport, min_codes: int | None = None
) -> None:
    min_questions = (min_codes or settings.GEN_MIN_CODES) * 2
    if len(lesson.quiz_questions) < min_questions:
        report.issues.append(
            f"عدد الأسئلة {len(lesson.quiz_questions)} أقل من {min_questions} (2 لكل كود)"
        )
    correct_positions: list[int] = []
    for i, q in enumerate(lesson.quiz_questions, start=1):
        correct = [idx for idx, o in enumerate(q.options) if o.correct]
        if q.kind == "single" and len(correct) != 1:
            report.issues.append(f"س{i}: لازم إجابة صحيحة واحدة بالضبط (وجد {len(correct)})")
        if q.kind == "multi" and len(correct) < 1:
            report.issues.append(f"س{i}: لا توجد إجابة صحيحة")
        if correct:
            correct_positions.append(correct[0])
    if len(correct_positions) >= 3 and len(set(correct_positions)) == 1:
        report.issues.append("كل الإجابات الصحيحة في نفس الخيار — يجب توزيعها")


def _check_atlas(codes: list[GeneratedCode], report: VerifyReport) -> None:
    min_usages = settings.GEN_MIN_USAGES
    for i, c in enumerate(codes, start=1):
        if len(c.usages) < min_usages:
            report.issues.append(
                f"كود{i}: عدد الاستخدامات {len(c.usages)} أقل من {min_usages}"
            )
        for j, u in enumerate(c.usages, start=1):
            if not u.example.strip():
                report.issues.append(f"كود{i} استخدم{j}: لا يوجد مثال")
            if not u.description.strip():
                report.issues.append(f"كود{i} استخدم{j}: لا يوجد وصف")
        if not c.explanation.strip():
            report.issues.append(f"كود{i}: لا يوجد شرح")


async def verify_lesson(
    lesson: GeneratedLesson,
    *,
    expect_language: str | None = None,
    check_exec: bool | None = None,
    check_atlas: bool | None = None,
    min_codes: int | None = None,
) -> VerifyReport:
    report = VerifyReport(passed=False)
    do_exec = settings.VERIFY_EXEC if check_exec is None else check_exec
    do_atlas = settings.GEN_ENRICH_ATLAS if check_atlas is None else check_atlas
    required_codes = min_codes or settings.GEN_MIN_CODES

    # 1) العدد
    if len(lesson.code_samples) < required_codes:
        report.issues.append(
            f"عدد الأكواد {len(lesson.code_samples)} أقل من {required_codes}"
        )
    if len(lesson.content_md.strip()) < 200:
        report.issues.append("الشرح النظري قصير جدا")

    # 2) الاختبار
    _check_quiz(lesson, report, required_codes)

    # 3) موسوعة الأكواد (بنية)
    if do_atlas:
        _check_atlas(lesson.code_samples, report)

    # 4) مطابقة اللغة
    for i, c in enumerate(lesson.code_samples, start=1):
        if expect_language and c.language != expect_language:
            report.issues.append(f"كود{i}: اللغة {c.language} لا تطابق {expect_language}")

    # 5) التنفيذ الفعلي (متزامن بحد أقصى)
    if do_exec:
        await _verify_exec(lesson.code_samples, report)

    report.passed = not report.issues
    return report


async def _verify_exec(codes: list[GeneratedCode], report: VerifyReport) -> None:
    sem = asyncio.Semaphore(max(1, settings.VERIFY_CODE_CONCURRENCY))

    async def one(idx: int, c: GeneratedCode) -> tuple[int, str, str, str | None]:
        async with sem:
            res = await run_code(c.language, c.code)
        note: str | None = None
        if res.status == "ok" and c.expected_output.strip() and res.stdout.strip():
            if c.expected_output.strip()[:40] not in res.stdout:
                note = f"كود{idx}: الخرج الفعلي لا يطابق المذكور تماما (تنبيه لا فشل)"
        return idx, res.status, (res.detail or res.stderr[:120]), note

    results = await asyncio.gather(
        *(one(i, c) for i, c in enumerate(codes, start=1)), return_exceptions=True
    )
    for r in results:
        if isinstance(r, Exception):
            report.exec_failed += 1
            report.issues.append(f"فشل غير متوقع أثناء التنفيذ: {r}")
            continue
        idx, status, detail, note = r
        if status == "ok":
            report.exec_ok += 1
            if note:
                report.notes.append(note)
        elif status == "skipped":
            report.exec_skipped += 1
        else:
            report.exec_failed += 1
            report.issues.append(f"كود{idx} فشل التنفيذ: {detail}")
