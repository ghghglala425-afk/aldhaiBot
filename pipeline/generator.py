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

SYSTEM = """أنت خبير تعليمي عالمي في البرمجة والأمن السيبراني، تكتب دروسا عربية عميقة ودقيقة وعملية.
أرجع كائن JSON واحدا فقط (بلا أي نص حوله) بالبنية التالية:
{
  "title": "عنوان الدرس",
  "summary": "ملخص من سطرين يوضّح ماذا سيفهم المتعلم ولماذا يهمه",
  "objectives": ["هدف1", "هدف2"],
  "key_points": ["نقطة مفتاحية1", "نقطة مفتاحية2"],
  "memory_hook": "جملة واحدة سهلة الحفظ تلخّص الدرس كله",
  "prerequisites": ["معرفة سابقة1"],
  "further_reading": ["مصدر أو موضوع للتوسّع"],
  "content_md": "الشرح الموسّع بصيغة Markdown",
  "difficulty": "beginner|intermediate|advanced",
  "est_minutes": 25,
  "code_samples": [
    {"language": "python", "title": "عنوان المثال", "code": "الكود الفعلي", "explanation": "شرح تفصيلي لما يفعله كل جزء", "expected_output": "الخرج المتوقع"}
  ],
  "quiz_questions": [
    {"text": "نص السؤال", "kind": "single", "options": [{"text":"خيار","correct":true},{"text":"خيار","correct":false}], "explanation": "لماذا هذه الإجابة صحيحة والأخرى خاطئة"}
  ]
}
قواعد إلزامية:
- اكتب كل الكود بلغة %s فقط، وكل مثال قابل للتشغيل فعلا ويطبع مخرجا.
- عدد أمثلة الكود %d على الأقل.
- لكل كود سؤالان اختبار على الأقل (إجمالي %d سؤالا كحد أدنى).
- لكل سؤال خياران فأكثر، ووزّع الإجابات الصحيحة على مواضع مختلفة.
- لا تستخدم مكتبات غير مذكورة في المحتوى، ولا كود يحتاج شبكة أو ملفات خارجية.
- الشرح بالعربية الفصحى المبسطة، مع شرح المصطلح الإنجليزي عند أول ظهور له.

قواعد العمق (الأهم):
- content_md يجب أن يكون درسا كاملا حقيقيا لا ملخصا: **%d حرف على الأقل** (المثالي أكثر من ذلك).
- استخدم هذه الأقسام بالترتيب وبالعناوين الحرفية:
  `## المفهوم ببساطة` ثم `## لماذا هذا مهم؟` ثم `## المتطلبات والمصطلحات` ثم
  `## التفاصيل خطوة بخطوة` ثم `## مثال عملي مشروح` ثم `## أخطاء شائعة` ثم
  `## الأمان في هذا الموضوع` ثم `## تمرين تطبيقي` ثم `## الخلاصة`.
- تحت كل عنوان: سطر اقتباس يبدأ بـ `> ` يلخّص الفكرة، ثم **فقرة كاملة من 4 أسطر على الأقل**،
  ثم 3 إلى 5 نقاط تبدأ بـ `- `. لا تكتب سطرا واحدا تحت أي عنوان.
- في «التفاصيل خطوة بخطوة» اكتب 5 خطوات مرقّمة على الأقل، كل خطوة جملتان تشرحان ماذا ولماذا.
- في «المثال العملي» اشرح سيناريو واقعيا، ثم ماذا يحدث عند التشغيل، ثم 4 ملاحظات على الخرج.
- في «أخطاء شائعة» اكتب 4 أخطاء بصيغة: `- الخطأ: ... — الحل: ...`.
- في «التمرين» اكتب مهمة واحدة واضحة + 3 تلميحات + النتيجة المتوقعة.
- استخدم `**كلمة مفتاحية**` للمصطلحات و`` `كود` `` للمعرّفات والأوامر، ونوّع صياغتك بلا تكرار.
- عند المقارنة استخدم نقاطا: `- س: ... — ص: ...` (لا تُخرج جداول).
- key_points: من 5 إلى 7 نقاط قصيرة، كل نقطة فكرة مستقلة قابلة للتذكر.
- memory_hook: جملة واحدة (أقل من 15 كلمة) تربط المفهوم بصورة ذهنية.
- objectives: أهداف إجرائية تبدأ بفعل (افهم، اكتب، طبّق، حلّل).
- explanation لكل كود: 3 أسطر على الأقل تشرح الفكرة والسبب والنتيجة، لا وصفا سطحيا.
- expected_output: خرج حقيقي دقيق يطابق الكود تماما."""


def _build_user(
    topic: str,
    language: str,
    difficulty: str,
    context: str = "",
    *,
    min_codes: int,
    min_chars: int,
) -> str:
    min_questions = min_codes * 2
    return (
        f"اكتب درسا كاملا بعنوان يقارب: «{topic}»\n"
        f"لغة البرمجة: {language}\n"
        f"المستوى: {difficulty}\n"
        f"{('سياق إضافي: ' + context) if context else ''}\n"
        f"تذكّر: {min_codes} مثال كود على الأقل وكلها تعمل بلا أخطاء.\n"
        f"مهم جدا: لكل كود سؤالان اختبار على الأقل (إجمالي {min_questions} سؤالا على الأقل).\n"
        f"مهم جدا: content_md شرح موسّع لا يقل عن {min_chars} حرف، بفقرات كاملة ونقاط تحت كل قسم، "
        "وليس مجرد سطور قصيرة. الشرح يجب أن يكفي متعلما مبتدئا لفهم الموضوع وتطبيقه بلا مساعدة."
    )


async def generate_lesson(
    topic: str,
    language: str,
    difficulty: str = "beginner",
    *,
    context: str = "",
    fast: bool = False,
) -> tuple[GeneratedLesson, VerifyReport]:
    """يولّد الدرس، يتحقق منه، ويصلح تلقائيا حتى الاجتياز أو نفاد المحاولات.

    fast=True: مسار الفتح الفوري — أمثلة أقل، محاولة إصلاح واحدة، ونموذج
    سريع إن توفّر، بلا إثراء موسوعة الأكواد (يُؤجَّل للخلفية).
    """
    min_codes = settings.GEN_FAST_CODES if fast else settings.GEN_MIN_CODES
    min_chars = settings.GEN_FAST_MIN_CHARS if fast else settings.GEN_MIN_CHARS
    system = SYSTEM % (language, min_codes, min_codes * 2, min_chars)
    repairs = 1 if fast else settings.GEN_MAX_REPAIRS
    model = settings.outline_model if fast else None
    report = VerifyReport(passed=False)
    lesson: GeneratedLesson | None = None

    for attempt in range(1, repairs + 2):
        if attempt == 1:
            user = _build_user(
                topic, language, difficulty, context, min_codes=min_codes, min_chars=min_chars
            )
        else:
            assert lesson is not None
            user = (
                "الدرس السابق فشل في التحقق. أصلح المشاكل التالية وأعد إرجاع JSON كامل صحيح:\n- "
                + "\n- ".join(report.issues[:15])
                + "\n\nالدرس السابق:\n"
                + json.dumps(lesson.model_dump(), ensure_ascii=False)[:6000]
            )

        raw = await chat_json(
            system,
            user,
            model=model,
            max_retries=1 if fast else None,
            timeout=150.0 if fast else None,
        )
        lesson = GeneratedLesson.model_validate(raw)
        report = await verify_lesson(
            lesson, expect_language=language, check_atlas=False, min_codes=min_codes
        )
        log.info("محاولة %s: %s", attempt, report.summary())
        if report.passed:
            break

    assert lesson is not None
    if not report.passed:
        return lesson, report

    # المرحلة الثانية: إثراء كل كود بموسوعة كاملة (تشريح + استخدامات + أخطاء + أمان)
    if settings.GEN_ENRICH_ATLAS and not fast:
        log.info("إثراء %s كود بموسوعة الأكواد…", len(lesson.code_samples))
        lesson = lesson.model_copy(
            update={"code_samples": await enrich_codes(lesson.code_samples, language)}
        )
        report = await verify_lesson(
            lesson, expect_language=language, check_exec=False, check_atlas=True
        )
        log.info("تحقق الموسوعة: %s", report.summary())

    return lesson, report
