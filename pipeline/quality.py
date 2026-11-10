# -*- coding: utf-8 -*-
"""تحسين جودة الاختبار المولّد قبل التحقق (بلا استهلاك إضافي للـAI)."""
from __future__ import annotations

from pipeline.schema import GeneratedLesson


def balance_quiz(lesson: GeneratedLesson) -> int:
    """يوزّع الإجابات الصحيحة على مواضع مختلفة ويصلح تعدّد الصحيح.

    نماذج LLM تميل إلى وضع الإجابة الصحيحة أولاً في كل الأسئلة، وبوابة
    التحقق ترفض ذلك. بدل إهدار استدعاء AI جديد، ندوّر الخيارات (بلا تغيير
    معناها) ونُبقي إجابة واحدة فقط في أسئلة single.

    يعيد عدد التعديلات (للتسجيل فقط).
    """
    changed = 0

    # 1) سؤال single لا يجوز أن يحمل أكثر من إجابة صحيحة.
    for question in lesson.quiz_questions:
        if question.kind != "single":
            continue
        seen = False
        for option in question.options:
            if not option.correct:
                continue
            if seen:
                option.correct = False
                changed += 1
            else:
                seen = True

    # 2) إن كانت كل الإجابات في الموضع نفسه (3 أسئلة فأكثر) ندوّر الخيارات.
    positions: list[int | None] = []
    for question in lesson.quiz_questions:
        positions.append(
            next((i for i, o in enumerate(question.options) if o.correct), None)
        )
    valid = [p for p in positions if p is not None]
    if len(valid) >= 3 and len(set(valid)) == 1:
        for qi, question in enumerate(lesson.quiz_questions):
            if len(question.options) < 2:
                continue
            shift = qi % len(question.options)
            if shift:
                question.options = question.options[shift:] + question.options[:shift]
        changed += len(lesson.quiz_questions)

    return changed
