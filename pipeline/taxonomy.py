# -*- coding: utf-8 -*-
"""خريطة المنهج (Taxonomy) — تُشتق منها كورسات ومراحل ودروس قابلة للتوليد."""
from __future__ import annotations

from dataclasses import dataclass, field

STAGES = ["الأساسيات", "المتوسط", "المتقدم"]

_TOPICS: dict[str, list[list[str]]] = {
    "الأساسيات": [
        "المتغيرات وأنواع البيانات", "العمليات والتحويلات", "الشروط والقرارات",
        "الحلقات والتكرار", "الدوال والوسائط", "المصفوفات والقوائم",
        "القواميس والخرائط", "معالجة الأخطاء",
    ],
    "المتوسط": [
        "التعابير النمطية", "تجزئة كلمات المرور", "التشفير المتماثل",
        "طلبات الشبكة والـHTTP", "معالجة JSON", "التعامل مع الملفات",
        "الخيوط والتزامن", "اختبار الأكواد",
    ],
    "المتقدم": [
        "أتمتة المهام الأمنية", "تحليل السجلات", "فحص الثغرات",
        "تحليل الحزم الشبكية", "التشفير غير المتماثل", "الاستغلال الأخلاقي",
        "بناء أدوات سطر الأوامر", "مشروع تطبيقي شامل",
    ],
}

# اللغات التي نبني لها كورسا في مسار الأمن السيبراني
SECURITY_COURSES: list[dict] = [
    {"slug": "python-security", "title": "بايثون للأمن السيبراني", "icon": "🐍", "language": "python"},
    {"slug": "javascript-security", "title": "جافاسكربت وأمن الويب", "icon": "🌐", "language": "javascript"},
    {"slug": "bash-security", "title": "باش لأتمتة الأمن", "icon": "🖥️", "language": "bash"},
    {"slug": "sql-security", "title": "SQL وحقن قواعد البيانات", "icon": "🗄️", "language": "sql"},
    {"slug": "c-security", "title": "لغة C واستغلال الذاكرة", "icon": "⚙️", "language": "c"},
    {"slug": "php-security", "title": "PHP وأمن تطبيقات الويب", "icon": "🐘", "language": "php"},
]


@dataclass
class LessonPlan:
    course_slug: str
    course_title: str
    icon: str
    language: str
    stage: str
    stage_index: int
    topic: str
    lesson_index: int
    difficulty: str
    tags: list[str] = field(default_factory=list)
    # حقول التوسّع العالمي (اختيارية — تُملأ لخطط اللغات)
    language_name: str = ""
    outline_title: str = ""
    slug: str = ""
    order_index: int = 0


_DIFF = {"الأساسيات": "beginner", "المتوسط": "intermediate", "المتقدم": "advanced"}


def _slugify(text: str) -> str:
    out = []
    for ch in text:
        if ch.isalnum():
            out.append(ch)
        elif ch in " -_":
            out.append("-")
    slug = "".join(out).strip("-").lower()
    return slug or "lesson"


def iter_lessons(course_slugs: list[str] | None = None) -> list[LessonPlan]:
    """يُرجع خطة كل الدروس في المنهج (أو لكورسات محددة)."""
    plans: list[LessonPlan] = []
    for course in SECURITY_COURSES:
        if course_slugs and course["slug"] not in course_slugs:
            continue
        li = 0
        for si, stage in enumerate(STAGES, start=1):
            for topic in _TOPICS[stage]:
                li += 1
                plans.append(
                    LessonPlan(
                        course_slug=course["slug"],
                        course_title=course["title"],
                        icon=course["icon"],
                        language=course["language"],
                        stage=stage,
                        stage_index=si,
                        topic=topic,
                        lesson_index=li,
                        difficulty=_DIFF[stage],
                        tags=[course["slug"], _slugify(stage), f"lesson-{li}"],
                    )
                )
    return plans


def lesson_slug(plan: LessonPlan) -> str:
    if plan.slug:
        return plan.slug
    return f"{_slugify(plan.stage)}-{plan.lesson_index:02d}-{_slugify(plan.topic)}"


# =====================================================================
#  التوسّع العالمي: 10 مراحل × 100 درس لكل لغة (قابل للضبط بالبيئة)
# =====================================================================
STAGE_TITLES: list[tuple[str, str]] = [
    ("الأساسيات", "beginner"),
    ("التحكّم والمنطق", "beginner"),
    ("الدوال والوحدات", "beginner"),
    ("هياكل البيانات", "intermediate"),
    ("الملفات والشبكات", "intermediate"),
    ("التزامن والأداء", "intermediate"),
    ("الأمان التطبيقي", "advanced"),
    ("التشفير والأسرار", "advanced"),
    ("الهندسة والأدوات", "advanced"),
    ("مشروع تطبيقي شامل", "advanced"),
]

SKILLS: list[str] = [
    "المتغيّرات وأنواع البيانات",
    "المعاملات والتحويلات",
    "الشروط والقرارات",
    "الحلقات والتكرار",
    "الدوال والوسائط",
    "السلاسل النصية",
    "المصفوفات والقوائم",
    "القواميس وبنى الخرائط",
    "المجموعات والتكرار عليها",
    "الوحدات والحزم",
    "معالجة الأخطاء",
    "المدخلات والمخرجات",
    "التعابير النمطية",
    "الملفات والأدلة",
    "JSON والبيانات المهيكلة",
    "التواريخ والأوقات",
    "الأصناف والكائنات",
    "الوراثة والتجريد",
    "الواجهات والعقود",
    "الخيوط والتزامن",
    "الشبكات و HTTP",
    "قواعد البيانات والاستعلامات",
    "اختبار الأكواد",
    "الأداء والتحسين",
    "البناء والتوزيع",
]

VARIANTS: list[str] = [
    "المفاهيم والأنماط",
    "تطبيق عملي",
    "أخطاء شائعة وتصحيحها",
    "الجانب الأمني والدفاعي",
]

_ICON_BY_PARADIGM = {
    "functional": "🧮",
    "low-level": "⚙️",
    "scripting": "🖥️",
    "declarative": "🗄️",
    "markup": "📄",
    "stylesheet": "🎨",
    "config": "🧾",
    "pattern": "🔎",
    "esoteric": "🌀",
    "statistical": "📈",
    "oop": "🧩",
}


def language_icon(slug: str, paradigm: str | None = None) -> str:
    if slug in {"python", "javascript", "typescript"}:
        return "🐍" if slug == "python" else "🌐"
    if slug in {"c", "cpp", "rust", "zig"}:
        return "⚙️"
    if slug in {"php", "ruby", "perl"}:
        return "🐘" if slug == "php" else "💎"
    if slug in {"bash", "powershell"}:
        return "🖥️"
    if slug in {"sql"}:
        return "🗄️"
    return _ICON_BY_PARADIGM.get((paradigm or "").lower(), "📘")


def stage_titles(stages: int | None = None) -> list[tuple[str, str]]:
    from core.config import settings

    n = stages or settings.GEN_STAGES
    out = list(STAGE_TITLES[: max(1, n)])
    while len(out) < max(1, n):  # لو زاد العدد عن العشرة نولّد مراحل عامة إضافية
        i = len(out) + 1
        out.append((f"مرحلة متقدّمة {i}", "advanced"))
    return out


def language_course_slug(language: str) -> str:
    return f"{language}-mastery"


def language_course_title(name_ar: str) -> str:
    return f"إتقان {name_ar}"


def iter_language_lessons(
    language: str,
    name_ar: str,
    *,
    icon: str = "📘",
    stages: int | None = None,
    per_stage: int | None = None,
) -> list[LessonPlan]:
    """يبني خطة كاملة للغة: (مراحل × دروس) بمواضيع حتمية فريدة.

    تُستخدم كأساس لمخطط (Outline) قابل للتصفّح فورا، ثم يُولَّد محتواها عند الطلب.
    """
    from core.config import settings

    n_stages = max(1, stages or settings.GEN_STAGES)
    n_per = max(1, per_stage or settings.GEN_LESSONS_PER_STAGE)
    defined = stage_titles(n_stages)
    course_slug = language_course_slug(language)
    course_title = language_course_title(name_ar)

    plans: list[LessonPlan] = []
    global_order = 0
    for si in range(1, n_stages + 1):
        stage_title, difficulty = defined[si - 1]
        idx = 0
        for skill in SKILLS:
            for variant in VARIANTS:
                idx += 1
                if idx > n_per:
                    break
                global_order += 1
                topic = f"{stage_title} — {skill} ({variant})"
                slug = f"s{si:02d}-l{idx:03d}-{_slugify(skill)}"
                plans.append(
                    LessonPlan(
                        course_slug=course_slug,
                        course_title=course_title,
                        icon=icon,
                        language=language,
                        stage=stage_title,
                        stage_index=si,
                        topic=topic,
                        lesson_index=idx,
                        difficulty=difficulty,
                        tags=[language, _slugify(stage_title), _slugify(skill)],
                        language_name=name_ar,
                        outline_title=topic,
                        slug=slug,
                        order_index=global_order,
                    )
                )
            if idx >= n_per:
                break
        # لو احتجنا دروسا أكثر من ناتج الضرب (مثلا per_stage>100) نكمل بتوليد مرقّم
        while idx < n_per:
            idx += 1
            global_order += 1
            topic = f"{stage_title} — تدريب إضافي رقم {idx}"
            slug = f"s{si:02d}-l{idx:03d}-extra"
            plans.append(
                LessonPlan(
                    course_slug=course_slug,
                    course_title=course_title,
                    icon=icon,
                    language=language,
                    stage=stage_title,
                    stage_index=si,
                    topic=topic,
                    lesson_index=idx,
                    difficulty=difficulty,
                    tags=[language, _slugify(stage_title)],
                    language_name=name_ar,
                    outline_title=topic,
                    slug=slug,
                    order_index=global_order,
                )
            )
    return plans
