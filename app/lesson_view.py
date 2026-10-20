# -*- coding: utf-8 -*-
"""مُنسّق الدروس الاحترافي — نقاط، ألوان، خطافات ذاكرة، بطاقة مراجعة.

الهدف: سهولة التركيز والحفظ عبر:
  • تدرّج بصري واضح (ترويسة → أهداف → نقاط → كود → تنبيهات → بطاقة مراجعة)
  • رموز تعبيرية كلون (لا ألوان حقيقية في تيليجرام — الرموز هي البديل)
  • نقاط مرقّمة وقوائم قصيرة (تزيد الاستيعاب)
  • «خطّاف ذاكرة» memorable hook لكل درس
  • «بطاقة مراجعة» ل.REVISION السريعة
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass

# =============================================================================
#  الرموز التعبيرية = الألوان (تيليجرام لا يدعم ألوان النص)
# =============================================================================
EMOJI = {
    "primary": "🔵",     # أساسي
    "success": "🟢",     # نجاح / صحيح
    "warning": "🟡",     # تحذير
    "danger": "🔴",      # خطر / خطأ
    "info": "🔵",        # معلومة
    "purple": "🟣",      # متقدم
    "orange": "🟠",      # مهم
    "star": "⭐",         # مميّز
    "fire": "🔥",         # تحدي
    "brain": "🧠",        # ذاكرة
    "target": "🎯",       # هدف
    "lightbulb": "💡",    # فكرة
    "shield": "🛡️",       # أمن
    "rocket": "🚀",       # ابدأ
    "book": "📚",         # محتوى
    "code": "💻",         # كود
    "check": "✅",         # صحيح
    "cross": "❌",        # خطأ
    "pin": "📌",          # تثبيت
    "clock": "⏱️",        # وقت
    "level": "📊",         # مستوى
    "key": "🔑",          # مفتاح
    "chain": "⛓️",        # سلسلة
    "repeat": "🔁",        # تكرار
    "palette": "🎨",       # تنسيق
    "chart": "📈",         # تقدم
    "note": "📝",         # ملاحظة
    "gift": "🎁",         # مفاجأة
    "flag": "🚩",         # تحذير مهم
}

# فواصل أفقية ملونة
SEP = "━━━━━━━━━━━━━━━━━━━━━"

# =============================================================================
#  أدوات مساعدة
# =============================================================================
def esc(text: str) -> str:
    """تهريب HTML — يضمن ألا يكسر النص رموز تيليجرام."""
    if not text:
        return ""
    return html.escape(str(text), quote=False)


def md_to_tg(text: str) -> str:
    """يحوّل Markdown مبسّط إلى HTML يدعمه تيليجرام."""
    if not text:
        return ""
    out = esc(text)
    # سطر --- divider
    out = re.sub(r"(?m)^\s*---\s*$", f"\n{SEP}\n", out)
    # عناوين
    out = re.sub(r"(?m)^###\s+(.+)$", r"\n<b>\1</b>\n", out)
    out = re.sub(r"(?m)^##\s+(.+)$", r"\n<u>\1</u>\n", out)
    out = re.sub(r"(?m)^#\s+(.+)$", r"\n<b>\1</b>\n", out)
    # غامق
    out = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", out)
    # مائل
    out = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"<i>\1</i>", out)
    # مشوّه / ~~
    out = re.sub(r"~~(.+?)~~", r"<s>\1</s>", out)
    # code inline
    out = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", out)
    # قوائم — نحافظ على المسافة البادئة أثناء الإحاطة
    out = re.sub(r"(?m)^[ \t]*[-•][ \t]+(.+)$", r"  ▫️ \1", out)
    out = re.sub(r"(?m)^[ \t]*(\d+)[.)][ \t]+(.+)$", r"  \1️⃣ \2", out)
    # blockquote
    out = re.sub(r"(?m)^&gt;\s?(.*)$", r"  <i>\1</i>", out)
    return out.strip()


def _bullets(items, emoji: str = "▫️", indent: str = "  ") -> str:
    """قائمة نقطية موحّدة (HTML mode — النصوص تُهرَّب)."""
    if not items:
        return ""
    lines = []
    for it in items:
        text = str(it).strip()
        if not text:
            continue
        lines.append(f"{indent}{emoji} {esc(text)}")
    return "\n".join(lines)


def _numbered(items, start: int = 1, indent: str = "  ") -> str:
    """قائمة مرقّمة (HTML mode — النصوص تُهرَّب)."""
    if not items:
        return ""
    lines = []
    for i, it in enumerate(items, start=start):
        text = str(it).strip()
        if not text:
            continue
        lines.append(f"{indent}<b>{i}.</b> {esc(text)}")
    return "\n".join(lines)

def _bar(percent: float, width: int = 10) -> str:
    """شريط تقدم بصري."""
    percent = max(0.0, min(100.0, float(percent)))
    filled = int(round(width * percent / 100))
    return "🟩" * filled + "⬜" * (width - filled)


@dataclass
class LessonView:
    """نتيجة تنسيق الدرس."""

    header: str = ""
    objectives: str = ""
    content: str = ""
    code_block: str = ""
    warnings: str = ""
    memory_hook: str = ""
    review_card: str = ""
    footer: str = ""


# =============================================================================
#  الأقسام
# =============================================================================
def render_header(
    title: str,
    summary: str = "",
    *,
    difficulty: str = "beginner",
    est_minutes: int = 25,
    lesson_number: int | None = None,
    total_lessons: int | None = None,
    progress_percent: float | None = None,
) -> str:
    """ترويسة الدرس — تدرّج بصري + شريط تقدم."""
    diff_map = {
        "beginner": ("🟢", "مبتدئ"),
        "intermediate": ("🟡", "متوسط"),
        "advanced": ("🔴", "متقدم"),
    }
    diff_emoji, diff_name = diff_map.get((difficulty or "").lower(), ("🔵", difficulty or ""))

    lines = [SEP]
    head = f"{EMOJI['book']} <b>{esc(title)}</b>"
    if lesson_number:
        total = f"/{total_lessons}" if total_lessons else ""
        head += f"  <i>(الدرس {lesson_number}{total})</i>"
    lines.append(head)
    lines.append(SEP)

    meta = [f"{diff_emoji} <b>{esc(diff_name)}</b>", f"{EMOJI['clock']} {int(est_minutes or 0)} دقيقة"]
    lines.append("  ".join(meta))

    if progress_percent is not None:
        lines.append("")
        lines.append(f"{EMOJI['chart']} {_bar(progress_percent)}  {int(progress_percent)}%")

    if summary:
        lines.append("")
        lines.append(f"{EMOJI['info']} <i>{esc(summary)}</i>")

    return "\n".join(lines)


def render_objectives(objectives) -> str:
    """الأهداف — نقاط مرقّمة بألوان."""
    items = [o for o in (objectives or []) if str(o).strip()]
    if not items:
        return ""
    lines = [
        "",
        f"{EMOJI['target']} <b>ماذا ستتعلّم؟</b>",
        SEP,
    ]
    for i, o in enumerate(items, start=1):
        lines.append(f"  <b>{i}️⃣</b> {esc(o)}")
    return "\n".join(lines)


def render_key_points(points) -> str:
    """نقاط المفتاح —结节 سريعة يسهل تذكرها."""
    items = [p for p in (points or []) if str(p).strip()]
    if not items:
        return ""
    lines = [
        "",
        f"{EMOJI['key']} <b>نقاط المفتاح</b>",
        SEP,
        _bullets(items, emoji=EMOJI["success"]),
    ]
    return "\n".join(lines)


def render_memory_hook(hook: str) -> str:
    """خطّاف الذاكرة — جملة واحدة تُثبَّت في الذاكرة."""
    if not hook or not hook.strip():
        return ""
    return "\n".join([
        "",
        f"{EMOJI['brain']} <b>احفظ هذه الجملة</b>",
        SEP,
        f"  <i>«{esc(hook.strip())}»</i>",
    ])


def render_warnings(gotchas, security_notes) -> str:
    """الأخطاء الشائعة + الملاحظات الأمنية."""
    out = []
    gotchas = [g for g in (gotchas or []) if str(g).strip()]
    security = [s for s in (security_notes or []) if str(s).strip()]

    if gotchas:
        out.append("")
        out.append(f"{EMOJI['warning']} <b>أخطاء شائعة — تجنّبها</b>")
        out.append(SEP)
        out.append(_bullets(gotchas, emoji=EMOJI["cross"]))
    if security:
        out.append("")
        out.append(f"{EMOJI['shield']} <b>تنبيه أمني</b>")
        out.append(SEP)
        out.append(_bullets(security, emoji=EMOJI["danger"]))
    return "\n".join(out)


def render_review_card(
    summary: str = "",
    key_points=None,
    memory_hook: str = "",
    next_step: str = "",
) -> str:
    """بطاقة المراجعة — ملخص سريع للحفظ."""
    lines = [
        "",
        f"{EMOJI['palette']} <b>بطاقة المراجعة</b>",
        SEP,
    ]
    if summary:
        lines.append(f"{EMOJI['note']} {esc(summary)}")
    points = [p for p in (key_points or []) if str(p).strip()]
    if points:
        lines.append("")
        lines.append(_bullets(points, emoji=EMOJI["check"], indent="  "))
    if memory_hook:
        lines.append("")
        lines.append(f"{EMOJI['brain']} <i>{esc(memory_hook)}</i>")
    if next_step:
        lines.append("")
        lines.append(f"{EMOJI['rocket']} <b>الخطوة التالية:</b> {esc(next_step)}")
    return "\n".join(lines)


def render_code_header(title: str, index: int, total: int, language: str = "") -> str:
    """ترويسة كتلة الكود."""
    head = f"{EMOJI['code']} <b>{esc(title)}</b>"
    if total:
        head += f"  <i>({index}/{total})</i>"
    if language:
        head += f"  <code>{esc(language)}</code>"
    return head


def render_code_block(code: str, language: str = "", index: int = 1, total: int = 0, title: str = "") -> str:
    """كتلة كود منسّقة مع ترويسة."""
    head = render_code_header(title or "مثال", index, total, language)
    return f"{head}\n<pre>{esc(code)}</pre>"


def render_footer(next_lesson: str = "", xp: int = 0, streak: int = 0) -> str:
    """تذييل الدرس."""
    parts = []
    if xp:
        parts.append(f"⭐ +{xp} XP")
    if streak:
        parts.append(f"🔥 {streak} يوم")
    line = "  ".join(parts)
    out = []
    if line:
        out.append("")
        out.append(line)
    if next_lesson:
        out.append("")
        out.append(f"{EMOJI['rocket']} <b>التالي:</b> {esc(next_lesson)}")
    return "\n".join(out)


def render_section(title: str, body: str, emoji: str = "📘") -> str:
    """قسم عام بعنوان."""
    if not body or not body.strip():
        return ""
    return "\n".join([
        "",
        f"{emoji} <b>{esc(title)}</b>",
        SEP,
        body,
    ])


def render_flashcard(card: dict, index: int, total: int, revealed: bool = False) -> str:
    """يعرض بطاقة مراجعة (أمام/ظهر)."""
    lines = [
        SEP,
        f"🃏 <b>بطاقة {index}/{total}</b>",
        SEP,
        "",
        f"❓ {esc(card.get('front', ''))}",
    ]
    if revealed:
        lines += [
            "",
            SEP,
            f"✅ <b>الجواب:</b> {esc(card.get('back', ''))}",
        ]
        if card.get("explanation"):
            lines.append(f"💡 {esc(card['explanation'])}")
    else:
        opts = card.get("options") or []
        for i, o in enumerate(opts, start=1):
            lines.append(f"  {i}️⃣ {esc(o)}")
        lines += ["", "<i>اضغط «👁️ اكشف الجواب» لرؤية الحل</i>"]
    return "\n".join(lines)


def split_markdown_sections(content_md: str) -> dict[str, str]:
    """يقسّم المحتوى إلى أقسام حسب العناوين (## ...)."""
    sections: dict[str, str] = {}
    if not content_md:
        return sections
    current = "المحتوى"
    buf: list[str] = []
    for line in content_md.splitlines():
        m = re.match(r"^\s{0,3}#{1,3}\s+(.+?)\s*$", line)
        if m:
            if buf:
                sections[current] = "\n".join(buf).strip()
            current = m.group(1).strip()
            buf = []
        else:
            buf.append(line)
    if buf:
        sections[current] = "\n".join(buf).strip()
    return sections
