# -*- coding: utf-8 -*-
"""تصدير الدروس: Markdown خام + ملف HTML بهوية بصرية جاهزة للطباعة PDF."""
from __future__ import annotations

import html
import io
import re

from telegram import Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes
from sqlalchemy import select

from core.db import SessionLocal
from core.logging import get_logger
from core.models import CodeSample, Lab, Lesson, Option, Question, Quiz, Stage
from app import tg

log = get_logger("bot.export")


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items) if items else "—"


def _fence(code: str, lang: str = "") -> str:
    return f"```{lang}\n{code.rstrip()}\n```"


async def _load(lesson_id: int):
    """يحمل الدرس وكل ملحقاته في جلسة واحدة."""
    async with SessionLocal() as s:
        lesson = await s.get(Lesson, lesson_id)
        if not lesson:
            return None
        codes = list(
            (await s.execute(
                select(CodeSample)
                .where(CodeSample.lesson_id == lesson_id)
                .order_by(CodeSample.order_index)
            )).scalars().all()
        )
        quiz = await s.scalar(select(Quiz).where(Quiz.lesson_id == lesson_id))
        questions: list[Question] = []
        options: dict[int, list[Option]] = {}
        if quiz:
            questions = list(
                (await s.execute(
                    select(Question)
                    .where(Question.quiz_id == quiz.id)
                    .order_by(Question.order_index)
                )).scalars().all()
            )
            for q in questions:
                options[q.id] = list(
                    (await s.execute(
                        select(Option)
                        .where(Option.question_id == q.id)
                        .order_by(Option.order_index)
                    )).scalars().all()
                )
        stage = await s.get(Stage, lesson.stage_id)
        labs = list(
            (await s.execute(select(Lab).where(Lab.lesson_id == lesson_id))).scalars().all()
        )
    return lesson, codes, questions, options, stage, labs


async def build_markdown(lesson_id: int) -> tuple[str, str] | None:
    data = await _load(lesson_id)
    if not data:
        return None
    lesson, codes, questions, options, stage, labs = data

    lines = [
        f"# {lesson.title}",
        "",
        f"> {lesson.summary or ''}",
        "",
        f"- **اللغة:** {lesson.language_slug or '—'}",
        f"- **المستوى:** {lesson.difficulty}",
        f"- **المدة التقديرية:** {lesson.est_minutes} دقيقة",
        f"- **النقاط:** {lesson.xp_reward}",
        f"- **المرحلة:** {stage.title if stage else '—'}",
        "",
    ]
    if lesson.objectives:
        lines += ["## الأهداف", _bullets(list(lesson.objectives)), ""]
    if lesson.prerequisites:
        lines += ["## المتطلبات السابقة", _bullets(list(lesson.prerequisites)), ""]
    if lesson.content_md:
        lines += ["## الشرح", lesson.content_md, ""]
    if lesson.key_points:
        lines += ["## نقاط المفتاح", _bullets(list(lesson.key_points)), ""]
    if lesson.memory_hook:
        lines += ["## خطّاف الذاكرة", f"> {lesson.memory_hook}", ""]

    if codes:
        lines.append("## أمثلة الأكواد")
        for i, c in enumerate(codes, start=1):
            lines.append(f"### {i}. {c.title}")
            lines.append(_fence(c.code, c.language))
            if c.explanation:
                lines.append(f"**الشرح:** {c.explanation}")
            if c.expected_output:
                lines.append(f"**الخرج المتوقع:** `{c.expected_output.strip()[:200]}`")
            if c.anatomy:
                lines.append("**التشريح السطري:**")
                lines += [
                    f"- السطر {a.get('line', '')}: `{a.get('code', '')}` — {a.get('explain', '')}"
                    for a in c.anatomy
                ]
            if c.usages:
                lines.append("**الاستخدامات:**")
                for u in c.usages:
                    lines.append(f"- **{u.get('name', '')}** — `{u.get('signature', '')}`: {u.get('description', '')}")
                    if u.get("example"):
                        lines.append(f"  - مثال: `{u['example']}` → `{u.get('output', '')}`")
            if c.gotchas:
                lines.append("**أخطاء شائعة:**")
                lines += [f"- {g}" for g in c.gotchas]
            if c.security_notes:
                lines.append("**ملاحظات أمنية:**")
                lines += [f"- {g}" for g in c.security_notes]
            lines.append("")

    if questions:
        lines.append("## الاختبار")
        for i, q in enumerate(questions, start=1):
            lines.append(f"**{i}. {q.text}**")
            for o in options.get(q.id, []):
                lines.append(f"- {'[x]' if o.is_correct else '[ ]'} {o.text}")
            if q.explanation:
                lines.append(f"  _تفسير:_ {q.explanation}")
            lines.append("")

    if labs:
        lines.append("## المختبرات")
        for item in labs:
            lines.append(f"- **{item.title}** ({item.kind}) — {item.description or ''}")
        lines.append("")

    if lesson.further_reading:
        lines += ["## للتوسّع أكثر", _bullets(list(lesson.further_reading)), ""]

    filename = f"lesson-{lesson_id}-{lesson.slug[:40]}.md"
    return "\n".join(lines), filename


# =============================================================================
#  HTML الأنيق
# =============================================================================
_CSS = """
:root{
  --bg:#070d1a; --card:#101a30; --card2:#0c1526; --ink:#e9efff; --muted:#9fb0d0;
  --cyan:#22d3ee; --violet:#a78bfa; --green:#34d399; --amber:#fbbf24; --red:#fb7185;
  --line:#22304d;
}
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(1200px 600px at 80% -10%,#16244a 0%,var(--bg) 55%);
  color:var(--ink);font-family:"Segoe UI","Tahoma",Arial,sans-serif;line-height:1.9;direction:rtl}
.wrap{max-width:900px;margin:0 auto;padding:28px 18px 60px}
.cover{position:relative;overflow:hidden;border:1px solid var(--line);border-radius:22px;
  padding:34px 30px;background:linear-gradient(135deg,#101b36 0%,#1a1440 55%,#0b1c33 100%);
  box-shadow:0 24px 60px rgba(0,0,0,.45)}
.cover:before{content:"";position:absolute;inset:auto -20% -60% auto;width:420px;height:420px;
  background:radial-gradient(circle,rgba(34,211,238,.22),transparent 65%)}
.brand{display:inline-flex;gap:8px;align-items:center;font-size:13px;letter-spacing:.4px;
  color:var(--cyan);border:1px solid rgba(34,211,238,.35);border-radius:999px;padding:5px 14px;
  background:rgba(34,211,238,.08)}
h1{margin:16px 0 8px;font-size:32px;line-height:1.45;
  background:linear-gradient(90deg,#e9efff,#a7f3ff 60%,#c4b5fd);-webkit-background-clip:text;
  background-clip:text;color:transparent}
.summary{color:#c9d6f2;font-size:16px;margin:0 0 18px}
.chips{display:flex;flex-wrap:wrap;gap:8px}
.chip{font-size:12.5px;color:#cfe0ff;border:1px solid var(--line);background:rgba(255,255,255,.03);
  border-radius:999px;padding:4px 12px}
.chip b{color:var(--cyan);font-weight:600}
.card{margin-top:18px;background:linear-gradient(180deg,var(--card),var(--card2));
  border:1px solid var(--line);border-radius:18px;padding:22px 24px;box-shadow:0 12px 34px rgba(0,0,0,.28)}
.card h2{margin:0 0 12px;font-size:20px;display:flex;align-items:center;gap:10px;color:#dbe7ff}
.card h2 .tag{font-size:12px;color:#7c8db3;font-weight:400}
.card h2:before{content:"";width:6px;height:24px;border-radius:8px;
  background:linear-gradient(180deg,var(--cyan),var(--violet))}
.card.obj{border-color:rgba(52,211,153,.35)}
.card.obj h2:before{background:linear-gradient(180deg,var(--green),#22d3ee)}
.card.warn{border-color:rgba(251,191,36,.35);background:linear-gradient(180deg,#231b0f,#161122)}
.card.warn h2:before{background:linear-gradient(180deg,var(--amber),#f97316)}
.card.sec{border-color:rgba(251,113,133,.35)}
.card.sec h2:before{background:linear-gradient(180deg,var(--red),#f43f5e)}
.content h3{color:var(--violet);margin:22px 0 8px;font-size:18px}
.content h2{font-size:21px;margin:26px 0 10px}
.content p{margin:8px 0;color:#d7e2f8}
.content ul,.content ol{margin:8px 22px 14px 0;padding:0}
.content li{margin:5px 0}
.content strong{color:#a7f3ff}
.content code{background:#0a1424;border:1px solid var(--line);border-radius:6px;
  padding:1px 6px;color:#a7f3ff;font-family:Consolas,monospace;font-size:13.5px}
blockquote{margin:12px 0;padding:10px 16px;border-right:4px solid var(--cyan);
  background:rgba(34,211,238,.07);border-radius:10px;color:#c7e6ff}
.hook{margin-top:18px;padding:16px 20px;border-radius:16px;border:1px dashed rgba(167,139,250,.55);
  background:linear-gradient(135deg,rgba(167,139,250,.14),rgba(34,211,238,.08));font-size:16px}
.hook b{color:var(--violet)}
.kp{list-style:none;margin:0;padding:0}
.kp li{margin:7px 0;padding-right:26px;position:relative}
.kp li:before{content:"✔";position:absolute;right:0;color:var(--green);font-weight:700}
.codecard{border:1px solid var(--line);border-radius:14px;overflow:hidden;margin:14px 0;background:#0a1322}
.codehead{display:flex;align-items:center;gap:10px;padding:9px 14px;background:#0e1a30;
  border-bottom:1px solid var(--line);font-size:13px;color:#bcd0ef}
.dots{display:flex;gap:5px}.dots i{width:9px;height:9px;border-radius:50%;display:block}
.dots i:nth-child(1){background:#fb7185}.dots i:nth-child(2){background:#fbbf24}.dots i:nth-child(3){background:#34d399}
.codehead .lang{margin-inline-start:auto;color:var(--cyan);font-family:Consolas,monospace}
pre{margin:0;padding:16px;overflow:auto;background:#060d19;color:#d7e2f8;
  font-family:Consolas,"Courier New",monospace;font-size:13px;line-height:1.65;direction:ltr;text-align:left}
.code-note{color:var(--muted);font-size:14px;margin:8px 2px}
.out{background:#07131f;border:1px solid var(--line);border-radius:10px;padding:10px 14px;
  font-family:Consolas,monospace;font-size:13px;color:#9ff5c8;direction:ltr;text-align:left;white-space:pre-wrap}
details{border:1px solid var(--line);border-radius:12px;padding:10px 14px;margin:10px 0;background:#0c1628}
summary{cursor:pointer;color:#cfe0ff}
details[open] summary{color:var(--cyan);margin-bottom:8px}
.opt{margin:5px 0;color:#c9d6f2}
.opt.correct{color:var(--green);font-weight:600}
.foot{margin-top:26px;text-align:center;color:#7c8db3;font-size:12.5px}
@media print{
  body{background:#fff;color:#111}
  .cover{background:#f6f8ff;box-shadow:none;border-color:#dbe3f5}
  h1{color:#1b2a4a;-webkit-text-fill-color:#1b2a4a}
  .card{background:#fff;box-shadow:none;border-color:#dbe3f5;break-inside:avoid}
  pre{background:#f4f7ff;color:#111;border:1px solid #dbe3f5}
  .summary,.content p,.content li{color:#243352}
  .chip{color:#243352;background:#eef3ff}
}
"""


def _md_inline(text: str) -> str:
    out = html.escape(text or "", quote=False)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", out)
    return out


def _md_to_html(md: str) -> str:
    """تحويل Markdown مبسّط إلى HTML منسّق للتصدير."""
    out: list[str] = []
    list_open: str | None = None

    def close_list() -> None:
        nonlocal list_open
        if list_open:
            out.append(f"</{list_open}>")
            list_open = None

    for line in (md or "").splitlines():
        s = line.rstrip()
        if not s.strip():
            close_list()
            continue
        m = re.match(r"^(#{1,4})\s+(.+)$", s.strip())
        if m:
            close_list()
            level = min(4, len(m.group(1)) + 1)
            out.append(f"<h{level}>{_md_inline(m.group(2))}</h{level}>")
            continue
        if s.strip() in {"---", "***", "___"}:
            close_list()
            out.append("<hr>")
            continue
        if s.lstrip().startswith(">"):
            close_list()
            out.append(f"<blockquote>{_md_inline(s.lstrip()[1:].strip())}</blockquote>")
            continue
        mc = re.match(r"^\s*[-•]\s*\[([xX ])\]\s*(.+)$", s)
        if mc:
            if list_open != "ul":
                close_list()
                out.append("<ul>")
                list_open = "ul"
            mark = "☑" if mc.group(1).lower() == "x" else "☐"
            out.append(f"<li>{mark} {_md_inline(mc.group(2))}</li>")
            continue
        mb = re.match(r"^\s*[-•]\s+(.+)$", s)
        if mb:
            if list_open != "ul":
                close_list()
                out.append("<ul>")
                list_open = "ul"
            out.append(f"<li>{_md_inline(mb.group(1))}</li>")
            continue
        mo = re.match(r"^\s*\d+[.)]\s+(.+)$", s)
        if mo:
            if list_open != "ol":
                close_list()
                out.append("<ol>")
                list_open = "ol"
            out.append(f"<li>{_md_inline(mo.group(1))}</li>")
            continue
        close_list()
        out.append(f"<p>{_md_inline(s)}</p>")
    close_list()
    return "\n".join(out)


def _chips(lesson, stage) -> str:
    diff = {"beginner": "🟢 مبتدئ", "intermediate": "🟡 متوسط", "advanced": "🔴 متقدم"}.get(
        (lesson.difficulty or "").lower(), lesson.difficulty or "—"
    )
    chips = [
        f"<span class='chip'><b>المستوى</b> {html.escape(diff)}</span>",
        f"<span class='chip'><b>اللغة</b> {html.escape(lesson.language_slug or '—')}</span>",
        f"<span class='chip'><b>المدة</b> {int(lesson.est_minutes or 0)} دقيقة</span>",
    ]
    if stage:
        chips.append(f"<span class='chip'><b>المرحلة</b> {html.escape(stage.title)}</span>")
    return "".join(chips)


async def build_export_html(lesson_id: int) -> tuple[str, str] | None:
    data = await _load(lesson_id)
    if not data:
        return None
    lesson, codes, questions, options, stage, labs = data

    parts: list[str] = [
        "<!doctype html>",
        "<html lang='ar' dir='rtl'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>{html.escape(lesson.title)}</title>",
        f"<style>{_CSS}</style></head><body><div class='wrap'>",
        "<header class='cover'>",
        "<span class='brand'>🎓 أكاديمية الأمن السيبراني والبرمجة</span>",
        f"<h1>{html.escape(lesson.title)}</h1>",
        f"<p class='summary'>{html.escape(lesson.summary or '')}</p>",
        f"<div class='chips'>{_chips(lesson, stage)}</div>",
        "</header>",
    ]

    if lesson.objectives:
        items = "".join(f"<li>{html.escape(str(o))}</li>" for o in lesson.objectives)
        parts.append(
            "<section class='card obj'><h2>🎯 ماذا ستتعلّم؟ <span class='tag'>الأهداف</span></h2>"
            f"<ul class='kp'>{items}</ul></section>"
        )
    if lesson.prerequisites:
        items = "".join(f"<li>{html.escape(str(o))}</li>" for o in lesson.prerequisites)
        parts.append(
            "<section class='card'><h2>🧩 المتطلبات السابقة</h2>"
            f"<ul class='kp'>{items}</ul></section>"
        )
    if lesson.content_md:
        parts.append(
            "<section class='card content'><h2>📖 الشرح الموسّع "
            "<span class='tag'>دراسة عميقة</span></h2>"
            f"{_md_to_html(lesson.content_md)}</section>"
        )
    if lesson.key_points:
        items = "".join(f"<li>{html.escape(str(p))}</li>" for p in lesson.key_points)
        parts.append(
            "<section class='card'><h2>🔑 نقاط المفتاح <span class='tag'>احفظها</span></h2>"
            f"<ul class='kp'>{items}</ul></section>"
        )
    if lesson.memory_hook:
        parts.append(
            f"<div class='hook'>🧠 <b>خطّاف الذاكرة:</b> «{html.escape(lesson.memory_hook)}»</div>"
        )

    if codes:
        cards = ["<section class='card'><h2>💻 أمثلة الأكواد <span class='tag'>تطبيق عملي</span></h2>"]
        for i, c in enumerate(codes, start=1):
            cards.append(
                "<div class='codecard'><div class='codehead'>"
                "<span class='dots'><i></i><i></i><i></i></span>"
                f"<span>{i}. {html.escape(c.title)}</span>"
                f"<span class='lang'>{html.escape(c.language or '')}</span></div>"
                f"<pre>{html.escape(c.code)}</pre></div>"
            )
            if c.explanation:
                cards.append(f"<p class='code-note'>💬 {html.escape(c.explanation)}</p>")
            if c.expected_output:
                cards.append(f"<div class='out'>الخرج المتوقع:\n{html.escape(c.expected_output)}</div>")
        cards.append("</section>")
        parts.append("".join(cards))

    gotchas: list[str] = []
    security: list[str] = []
    for c in codes:
        gotchas.extend(c.gotchas or [])
        security.extend(c.security_notes or [])
    gotchas = list(dict.fromkeys(gotchas))
    security = list(dict.fromkeys(security))
    if gotchas:
        items = "".join(f"<li>{html.escape(str(g))}</li>" for g in gotchas)
        parts.append(
            "<section class='card warn'><h2>⚠️ أخطاء شائعة — تجنّبها</h2>"
            f"<ul class='kp'>{items}</ul></section>"
        )
    if security:
        items = "".join(f"<li>{html.escape(str(g))}</li>" for g in security)
        parts.append(
            "<section class='card sec'><h2>🛡️ ملاحظات أمنية</h2>"
            f"<ul class='kp'>{items}</ul></section>"
        )

    if questions:
        quiz = ["<section class='card'><h2>✅ اختبر فهمك <span class='tag'>الاختبار</span></h2>"]
        for i, q in enumerate(questions, start=1):
            opts = "".join(
                f"<div class='opt{' correct' if o.is_correct else ''}'>"
                f"{'✔' if o.is_correct else '•'} {html.escape(o.text)}</div>"
                for o in options.get(q.id, [])
            )
            exp = f"<p class='code-note'>💡 {html.escape(q.explanation)}</p>" if q.explanation else ""
            quiz.append(
                f"<details><summary>{i}. {html.escape(q.text)}</summary>{opts}{exp}</details>"
            )
        quiz.append("</section>")
        parts.append("".join(quiz))

    if labs:
        items = "".join(
            f"<li><b>{html.escape(item.title)}</b> ({html.escape(item.kind)}) — "
            f"{html.escape(item.description or '')}</li>"
            for item in labs
        )
        parts.append(
            f"<section class='card'><h2>🧪 مختبرات عملية</h2><ul class='kp'>{items}</ul></section>"
        )

    if lesson.further_reading:
        items = "".join(f"<li>{html.escape(str(x))}</li>" for x in lesson.further_reading)
        parts.append(
            "<section class='card'><h2>📚 للتوسّع أكثر</h2>"
            f"<ul class='kp'>{items}</ul></section>"
        )

    parts.append(
        "<div class='foot'>أكاديمية الأمن السيبراني والبرمجة · "
        "افتح هذا الملف في المتصفح ثم اطبعه بصيغة PDF</div>"
    )
    parts.append("</div></body></html>")

    slug = re.sub(r"[^\w\-]+", "-", lesson.slug or f"lesson-{lesson_id}")[:48].strip("-")
    return "\n".join(parts), f"lesson-{lesson_id}-{slug}.html"


async def _send_export(update: Update, lesson_id: int) -> None:
    from app import ratelimit

    if not await ratelimit.guard(update, "export"):
        return
    res = await build_export_html(lesson_id)
    if not res:
        await tg.send_text(update.effective_message, "الدرس غير موجود.")
        return
    text, filename = res
    buf = io.BytesIO(text.encode("utf-8"))
    buf.name = filename
    await update.effective_message.reply_document(
        document=buf,
        filename=filename,
        caption=(
            f"📤 الدرس #{lesson_id} — ملف HTML أنيق\n"
            "افتحه في المتصفح ثم اطبعه PDF."
        ),
    )


async def export_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer("أُجهّز الملف…")
    await _send_export(update, int(q.data.split(":")[1]))


async def export_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    arg = (update.message.text or "").partition(" ")[2].strip()
    if not arg.isdigit():
        await tg.send_text(update.message, "الصيغة: /export رقم_الدرس (تجد الرقم بأمر /search أو داخل الكورس).")
        return
    await _send_export(update, int(arg))


def register_handlers(app) -> None:
    app.add_handler(CallbackQueryHandler(export_callback, pattern=r"^export:\d+$"))
    app.add_handler(CommandHandler("export", export_cmd))
