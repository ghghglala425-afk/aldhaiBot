# -*- coding: utf-8 -*-
"""تصدير الدروس كملفات Markdown/HTML قابلة للحفظ."""
from __future__ import annotations

import io

from telegram import Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes
from sqlalchemy import select

from core.db import SessionLocal
from core.logging import get_logger
from core.models import CodeSample, Lesson, Option, Question, Quiz, Stage, Lab
from app import tg

log = get_logger("bot.export")


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items) if items else "—"


def _fence(code: str, lang: str = "") -> str:
    return f"```{lang}\n{code.rstrip()}\n```"


async def build_markdown(lesson_id: int) -> tuple[str, str] | None:
    async with SessionLocal() as s:
        lesson = await s.get(Lesson, lesson_id)
        if not lesson:
            return None
        codes = list(
            (await s.execute(
                select(CodeSample).where(CodeSample.lesson_id == lesson_id).order_by(CodeSample.order_index)
            )).scalars().all()
        )
        quiz = await s.scalar(select(Quiz).where(Quiz.lesson_id == lesson_id))
        questions: list[Question] = []
        if quiz:
            questions = list(
                (await s.execute(
                    select(Question).where(Question.quiz_id == quiz.id).order_by(Question.order_index)
                )).scalars().all()
            )
        stage = await s.get(Stage, lesson.stage_id)
        labs = list((await s.execute(select(Lab).where(Lab.lesson_id == lesson_id))).scalars().all())

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
    if lesson.content_md:
        lines += ["## الشرح", lesson.content_md, ""]

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
            async with SessionLocal() as s2:
                opts = list(
                    (await s2.execute(
                        select(Option).where(Option.question_id == q.id).order_by(Option.order_index)
                    )).scalars().all()
                )
            for o in opts:
                lines.append(f"- {'[x]' if o.is_correct else '[ ]'} {o.text}")
            if q.explanation:
                lines.append(f"  _تفسير:_ {q.explanation}")
            lines.append("")

    if labs:
        lines.append("## المختبرات")
        for l in labs:
            lines.append(f"- **{l.title}** ({l.kind}) — {l.description or ''}")
        lines.append("")

    filename = f"lesson-{lesson_id}-{lesson.slug[:40]}.md"
    return "\n".join(lines), filename


async def _send_export(update: Update, lesson_id: int) -> None:
    from app import ratelimit

    if not await ratelimit.guard(update, "export"):
        return
    res = await build_markdown(lesson_id)
    if not res:
        await tg.send_text(update.effective_message, "الدرس غير موجود.")
        return
    text, filename = res
    buf = io.BytesIO(text.encode("utf-8"))
    buf.name = filename
    await update.effective_message.reply_document(
        document=buf, filename=filename, caption=f"📤 تصدير الدرس #{lesson_id}"
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
