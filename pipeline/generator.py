# -*- coding: utf-8 -*-
"""محرّك توليد الدروس بالذكاء الاصطناعي + حلقة إصلاح حتى الاجتياز."""
from __future__ import annotations

import json

from core.config import settings
from core.logging import get_logger
from pipeline.ai import chat_json
from pipeline.atlas import enrich_codes
from pipeline.schema import GeneratedLesson
from pipeline.verifier import VerifyReport, verify_lesson

log = get_logger("pipeline.generator")

SYSTEM = """أنت خبير تعليمي في البرمجة والأمن السيبراني، تكتب دروسا عربية دقيقة وعملية.
أرجع كائن JSON واحدا فقط (بلا أي نص حوله) بالبنية التالية:
{
  "title": "عنوان الدرس",
  "summary": "ملخص",
  "objectives": ["هدف1", "هدف2"],
  "key_points": ["نقطة مفتاحية1", "نقطة مفتاحية2"],
  "memory_hook": "جملة واحدة سهلة الحفظ تلخّص الدرس كله",
  "prerequisites": ["معرفة سابقة1"],
  "content_md": "شرح نظري مفصل بصيغة Markdown (200 حرف فأكثر)",
  "difficulty": "beginner|intermediate|advanced",
  "est_minutes": 25,
  "code_samples": [
    {"language": "python", "title": "عنوان المثال", "code": "الكود الفعلي", "explanation": "شرح سطري", "expected_output": "الخرج المتوقع"}
  ],
  "quiz_questions": [
    {"text": "نص السؤال", "kind": "single", "options": [{"text":"خيار","correct":true},{"text":"خيار","correct":false}], "explanation": "لماذا"}
  ]
}
قواعد إلزامية:
- اكتب كل الكود بلغة %s فقط.
- عدد أمثلة الكود %d على الأقل، كل مثال قابل للتشغيل فعلا ويطبع مخرجا.
- <b>لكل كود: اسأل سؤالين على الأقل</b> (إجمالي الأسئلة = عدد الأكواد × 2 كحد أدنى).
- لكل سؤال خياران فأكثر، ووزّع الإجابات الصحيحة على مواضع مختلفة.
- لا تستخدم مكتبات غير مذكورة في المحتوى، ولا كود يحتاج شبكة أو ملفات خارجية.
- الشرح بالعربية الفصحى المبسطة.

قواعد التنسيق (مهمة جدا لإظهار الدروس بشكل احترافي):
- <b>content_md</b> استخدم عناوين Markdown لتقسيم الشرح: `## المفهوم` ثم `## التفاصيل` ثم `## أمثلة` ثم `##小结`.
- تحت كل عنوان استخدم <b>نقاط قصيرة</b> (`- `) لا فقرات طويلة — يسهل القراءة والحفظ.
- <b>key_points</b>: من 3 إلى 6 نقاط، كل واحدة سطر واحد تختصر فكرة أساسية.
- <b>memory_hook</b>: جملة واحدة (أقل من 15 كلمة) سهلة الحفظ تربط مفهوم الدرس بصورة أو مقارنة.
- <b>objectives</b>: أهداف إجرائية تبدأ بفعل (افهم، اكتب، طبّق، حلّل).
- أضف جدول مقارنة بسيط بـ Markdown إن كان الدرس يقارن بين شيئين."""


def _build_user(topic: str, language: str, difficulty: str, context: str = "") -> str:
    min_questions = settings.GEN_MIN_CODES * 2
    return (
        f"اكتب درسا كاملا بعنوان يقارب: «{topic}»\n"
        f"لغة البرمجة: {language}\n"
        f"المستوى: {difficulty}\n"
        f"{('سياق إضافي: ' + context) if context else ''}\n"
        f"تذكّر: {settings.GEN_MIN_CODES} مثال كود على الأقل وكلها تعمل بلا أخطاء.\n"
        f"مهم جداً: لكل كود يجب إنشاء سؤالين اختبار على الأقل (إجمالي {min_questions} سؤال على الأقل)."
    )


async def generate_lesson(
    topic: str,
    language: str,
    difficulty: str = "beginner",
    *,
    context: str = "",
) -> tuple[GeneratedLesson, VerifyReport]:
    """يولّد الدرس، يتحقق منه، ويصلح تلقائيا حتى الاجتياز أو نفاد المحاولات."""
    system = SYSTEM % (language, settings.GEN_MIN_CODES, settings.GEN_MIN_CODES * 2)
    report = VerifyReport(passed=False)
    lesson: GeneratedLesson | None = None

    for attempt in range(1, settings.GEN_MAX_REPAIRS + 2):
        if attempt == 1:
            user = _build_user(topic, language, difficulty, context)
        else:
            assert lesson is not None
            user = (
                "الدرس السابق فشل في التحقق. أصلح المشاكل التالية وأعد إرجاع JSON كامل صحيح:\n- "
                + "\n- ".join(report.issues[:15])
                + "\n\nالدرس السابق:\n"
                + json.dumps(lesson.model_dump(), ensure_ascii=False)[:6000]
            )

        raw = await chat_json(system, user)
        lesson = GeneratedLesson.model_validate(raw)
        report = await verify_lesson(lesson, expect_language=language, check_atlas=False)
        log.info("محاولة %s: %s", attempt, report.summary())
        if report.passed:
            break

    assert lesson is not None
    if not report.passed:
        return lesson, report

    # المرحلة الثانية: إثراء كل كود بموسوعة كاملة (تشريح + استخدامات + أخطاء + أمان)
    if settings.GEN_ENRICH_ATLAS:
        log.info("إثراء %s كود بموسوعة الأكواد…", len(lesson.code_samples))
        lesson = lesson.model_copy(
            update={"code_samples": await enrich_codes(lesson.code_samples, language)}
        )
        report = await verify_lesson(
            lesson, expect_language=language, check_exec=False, check_atlas=True
        )
        log.info("تحقق الموسوعة: %s", report.summary())

    return lesson, report
