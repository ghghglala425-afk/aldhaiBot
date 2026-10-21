# -*- coding: utf-8 -*-
"""معالجات التعلّم: استعراض الكورسات والمراحل والدروس، وعرض الأكواد، وإجراء الاختبار."""
from __future__ import annotations

import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes
from sqlalchemy import func, select

from app import lesson_view as lv
from app.handlers.common import ai_error_text, animate_status
from app.keyboards import courses_kb
from app.pagination import clamp_page, nav_row, slice_page, total_pages
from core.db import SessionLocal
from core.learning import (
    STATUS_AVAILABLE,
    STATUS_IN_PROGRESS,
    STATUS_LOCKED,
    STATUS_PASSED,
    get_progress,
    labs_for_lesson,
    next_lesson_id,
    start_lesson,
    status_map,
    submit_quiz,
)
from core.logging import get_logger
from core.config import settings
from core.models import CodeSample, Course, Lesson, LessonAsset, Option, Question, Stage
from core.repo import get_user_by_telegram
from app import tg

log = get_logger("bot.learn")

_STATUS_ICON = {STATUS_PASSED: "✅", STATUS_AVAILABLE: "▶️", STATUS_LOCKED: "🔒", "in_progress": "⏳"}


async def _user(session, tg_id: int):
    return await get_user_by_telegram(session, tg_id)


async def courses_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _render_courses(update.effective_message)


async def _render_courses(message) -> None:
    async with SessionLocal() as s:
        res = await s.execute(
            select(Course).where(Course.is_published.is_(True)).order_by(Course.order_index, Course.id)
        )
        courses = [{"id": c.id, "title": c.title, "icon": c.icon} for c in res.scalars().all()]
    if not courses:
        await message.reply_text("📭 لا توجد كورسات منشورة بعد.")
        return
    kb = courses_kb(courses)
    await message.reply_text("📚 اختر كورسا:", reply_markup=kb)


async def courses_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    try:
        await q.edit_message_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001
        pass
    await _render_courses(update.effective_message)


COURSE_PER_PAGE = 30


async def course_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    parts = q.data.split(":")
    course_id = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 0
    async with SessionLocal() as s:
        course = await s.get(Course, course_id)
        if not course:
            await tg.edit_text(q, "الكورس غير موجود.")
            return
        user = await _user(s, update.effective_user.id)
        if not user:
            await tg.edit_text(q, "سجّل دخولك أولا عبر /start.")
            return
        rows = await status_map(s, user, course_id)
        stages = list(
            (await s.execute(
                select(Stage).where(Stage.course_id == course_id).order_by(Stage.order_index)
            )).scalars().all()
        )
        stage_of = {st.id: st.title for st in stages}

    pages = total_pages(len(rows), COURSE_PER_PAGE)
    page = clamp_page(page, pages)
    chunk = slice_page(rows, page, COURSE_PER_PAGE)

    lines = [f"*{tg.escape_md(course.title)}*  ({page + 1}/{pages})", ""]
    buttons: list[list[InlineKeyboardButton]] = []
    current_stage = None
    for r in chunk:
        lsn: Lesson = r["lesson"]
        st_title = stage_of.get(lsn.stage_id, "")
        if st_title != current_stage:
            current_stage = st_title
            lines.append(f"\n— *{tg.escape_md(st_title)}* —")
        icon = _STATUS_ICON.get(r["status"], "•")
        if lsn.status == "outline":
            icon = "🕓"
        elif r["status"] == STATUS_IN_PROGRESS:
            icon = "⏳"
        elif r["status"] == STATUS_PASSED:
            icon = "✅"
        lines.append(f"{icon} {tg.escape_md(lsn.title)}")
        buttons.append([InlineKeyboardButton(f"{icon} {tg.escape_md(lsn.title)[:46]}", callback_data=f"lesson:{lsn.id}")])
    buttons.append(nav_row(f"course:{course_id}", page, pages))
    buttons.append([InlineKeyboardButton("⬅️ الكورسات", callback_data="courses:0")])
    await tg.edit_text(q, 
        "\n".join(lines)[:3900],
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def _send_chunks(message, chunks: list[str]) -> None:
    for chunk in chunks:
        await message.reply_text(chunk, parse_mode=ParseMode.HTML)


async def _send_html_chunks(message, text: str, limit: int = 3800) -> None:
    """يقسّم نص HTML طويل إلى رسائل آمنة (بلا قطع وسوم إن أمكن)."""
    if not text:
        return
    async def _emit(part: str) -> None:
        if part.strip():
            await message.reply_text(
                part[:4000], parse_mode=ParseMode.HTML, disable_web_page_preview=True
            )

    buf = ""
    for line in text.splitlines(keepends=True):
        if len(line) > limit:
            await _emit(buf)
            buf = ""
            rest = line
            while len(rest) > 4000:
                cut = rest.rfind("\n", 0, 4000)
                if cut <= 0:
                    cut = 4000
                await _emit(rest[:cut])
                rest = rest[cut:]
            buf = rest
            continue
        if len(buf) + len(line) > limit:
            await _emit(buf)
            buf = ""
        buf += line
    await _emit(buf)



async def _flush_blocks(message, blocks: list[str]) -> None:
    """يرسل النصوص المتراكمة في رسائل أقل (حد تيليجرام ~4096)."""
    if not blocks:
        return
    text = "\n\n".join(b for b in blocks if b and b.strip())
    blocks.clear()
    if text:
        await _send_html_chunks(message, text)


async def _send_code_blocks(message, codes: list[CodeSample]) -> None:
    """رسالة واحدة لكل كود + صف أزرار تشغيل موحّد (رسائل أقل = فتح أسرع)."""
    total = len(codes)
    run_row: list[InlineKeyboardButton] = []
    for i, c in enumerate(codes, start=1):
        block = lv.render_code_block(c.code, c.language or "", i, total, c.title)
        tail = ""
        if c.explanation:
            tail += f"\n\n💬 <i>{lv.esc(c.explanation)}</i>"
        if c.expected_output:
            tail += (
                "\n\n📤 <b>الخرج المتوقع:</b>\n"
                f"<pre>{lv.esc(c.expected_output)}</pre>"
            )
        await _send_html_chunks(message, block + tail)
        run_row.append(
            InlineKeyboardButton(f"▶️ كود {i}", callback_data=f"runc:{c.id}")
        )
    if run_row:
        rows = [run_row[i : i + 2] for i in range(0, len(run_row), 2)]
        await message.reply_text(
            "▶️ <b>جرّب الأكواد بنفسك:</b>",
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(rows),
        )


async def run_code_sample(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يشغّل كود الدرس مباشرة في الـSandbox ويعرض النتيجة."""
    from pipeline.sandbox_runner import run_code
    from app import ratelimit

    q = update.callback_query
    if not await ratelimit.guard(update, "run"):
        return
    await q.answer("أشغّل الكود…")
    code_id = int(q.data.split(":")[1])
    async with SessionLocal() as s:
        c = await s.get(CodeSample, code_id)
    if not c:
        await tg.send_text(update.effective_message, "الكود غير موجود.")
        return
    msg = await update.effective_message.reply_text("⏳ أُشغّل الكود في بيئة معزولة…")
    try:
        res = await run_code(c.language, c.code, exec_enabled=True)
    except Exception as e:  # noqa: BLE001
        log.exception("تعذّر تشغيل كود الدرس #%s", code_id)
        await msg.edit_text(f"❌ تعذّر التشغيل: {str(e)[:180]}")
        return
    icon = {"ok": "✅", "error": "❌", "timeout": "⏰", "skipped": "⚠️"}.get(res.status, "•")
    body = f"{icon} <b>نتيجة التشغيل</b> — <code>{lv.esc(c.language)}</code>\n"
    if res.engine:
        body += f"المحرّك: <code>{lv.esc(res.engine)}</code>\n"
    if res.detail:
        body += f"ملاحظة: {lv.esc(res.detail)}\n"
    if res.stdout:
        body += f"\n<b>الخرج:</b>\n<pre>{lv.esc(res.stdout[:2200])}</pre>"
    if res.stderr:
        body += f"\n<b>الأخطاء:</b>\n<pre>{lv.esc(res.stderr[:1200])}</pre>"
    if res.status == "skipped":
        body += "\n<i>التنفيذ داخل Docker أو خدمة تنفيذ خارجية معزولة فقط — لا تنفيذ على مضيف الخادم.</i>"
    try:
        await msg.edit_text(body[:3900], parse_mode=ParseMode.HTML)
    except Exception:  # noqa: BLE001
        await tg.send_text(update.effective_message, body[:3900], parse_mode=ParseMode.HTML)


def _code_chunks(title: str, codes: list[CodeSample]) -> list[str]:
    """يجمع الأكواد في رسائل بحجم آمن مع إبرازها."""
    header = f"💻 *أكواد الدرس ({len(codes)})* — {title}\n"
    chunks: list[str] = []
    buf = header
    for i, c in enumerate(codes, start=1):
        block = f"\n<b>{i}. {c.title}</b>\n<pre>{_esc(c.code)}</pre>\n<i>{_esc(c.explanation)}</i>\n"
        if len(buf) + len(block) > 3500:
            chunks.append(buf)
            buf = ""
        buf += block
    if buf:
        chunks.append(buf)
    return chunks


def _esc(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class _ChatShim:
    """واجهة رسائل مختصرة تُتيح الدفع التلقائي للدرس بعد انتهاء التوليد."""

    def __init__(self, bot, chat_id: int, reply_to=None):
        self.bot = bot
        self.chat_id = int(chat_id)
        self.reply_to = getattr(reply_to, "message_id", None)

    async def reply_text(self, text, **kwargs):
        return await self.bot.send_message(self.chat_id, text, **kwargs)

    async def reply_audio(self, *a, **kw):
        return await self.bot.send_audio(self.chat_id, *a, **kw)

    async def reply_video(self, *a, **kw):
        return await self.bot.send_video(self.chat_id, *a, **kw)

    async def reply_photo(self, *a, **kw):
        return await self.bot.send_photo(self.chat_id, *a, **kw)

    async def reply_document(self, *a, **kw):
        return await self.bot.send_document(self.chat_id, *a, **kw)


_bg_tasks: set[asyncio.Task] = set()


def _spawn(coro) -> None:
    """يشغّل مهمة خلفية مع حفظ مرجع (كي لا يجمعها جامع المهملات)."""
    t = asyncio.create_task(coro)
    _bg_tasks.add(t)
    t.add_done_callback(_bg_tasks.discard)


async def lesson_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يعرض الدرس خلال أقل من ثانية، وإن كان مخططا يبنيه بالخلفية ويدفعه تلقائيا."""
    q = update.callback_query
    await q.answer()
    lesson_id = int(q.data.split(":")[1])
    chat_id = update.effective_chat.id
    bot = context.bot

    async with SessionLocal() as s:
        lesson = await s.get(Lesson, lesson_id)
        if not lesson:
            await tg.edit_text(q, "الدرس غير موجود.")
            return
        user = await _user(s, update.effective_user.id)
        if not user:
            await tg.edit_text(q, "سجّل دخولك أولا عبر /start.")
            return
        from core.learning import is_unlocked

        if not await is_unlocked(s, user, lesson):
            await tg.edit_text(
                q,
                "🔒 هذا الدرس مقفل. يجب إكمال الدرس السابق أولاً.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        is_outline = lesson.status == "outline" or not lesson.content_md
        try:
            await start_lesson(s, user.id, lesson_id)
        except Exception as e:  # noqa: BLE001
            log.warning("تعذّر تسجيل بدء الدرس: %s", e)

    # (1) شاشة الدرس تظهر فورا — بلا أي انتظار للذكاء الاصطناعي
    await _display_and_build(bot, chat_id, lesson_id, user=user, reply_to=update.effective_message)


async def _display_and_build(
    bot, chat_id: int, lesson_id: int, *, user=None, reply_to=None, notice=None
) -> None:
    """يعرض الدرس فورا ثم يبني محتواه أو يحضّر التالي في الخلفية."""
    async with SessionLocal() as s:
        lesson = await s.get(Lesson, lesson_id)
        if not lesson:
            return
        is_outline = lesson.status == "outline" or not lesson.content_md
    await _render_lesson(
        bot, chat_id, lesson_id, reply_to=reply_to, user=user, notice=notice
    )
    if is_outline:
        if settings.GEN_LAZY_ON_OPEN and settings.ai_configured:
            _spawn(_auto_build_and_push(bot, chat_id, lesson_id))
    else:
        _spawn(_prefetch_next(lesson_id))


async def _render_lesson(
    bot,
    chat_id: int,
    lesson_id: int,
    *,
    reply_to=None,
    notice: str | None = None,
    user=None,
) -> None:
    """يرسل شاشة الدرس كاملة (ترويسة/محتوى/أكواد/أزرار). لا يستدعي AI إطلاقا."""
    message = _ChatShim(bot, chat_id, reply_to)
    is_outline = False
    assets: list[LessonAsset] = []
    codes: list[CodeSample] = []
    labs = []
    progress_pct = None
    lesson_no = None
    total_lessons = None
    next_title = ""
    prev_id = None
    next_id = None
    lesson = None
    passed_before = False

    if notice:
        await tg.send_text(
            message, notice, parse_mode=ParseMode.HTML, disable_web_page_preview=True
        )

    async with SessionLocal() as s:
        lesson = await s.get(Lesson, lesson_id)
        if not lesson:
            return
        codes = list(
            (await s.execute(
                select(CodeSample).where(CodeSample.lesson_id == lesson_id).order_by(CodeSample.order_index)
            )).scalars().all()
        )
        labs = await labs_for_lesson(s, lesson_id)
        assets = list(
            (await s.execute(select(LessonAsset).where(LessonAsset.lesson_id == lesson_id))).scalars().all()
        )
        is_outline = lesson.status == "outline" or not lesson.content_md

        try:
            from core.learning import ordered_lessons

            stage = await s.get(Stage, lesson.stage_id)
            if stage:
                siblings = await ordered_lessons(s, stage.course_id)
                ids = [x.id for x in siblings]
                if lesson_id in ids:
                    idx = ids.index(lesson_id)
                    lesson_no = idx + 1
                    total_lessons = len(ids)
                    if idx + 1 < len(ids):
                        nxt = await s.get(Lesson, ids[idx + 1])
                        if nxt:
                            next_title = nxt.title
                            next_id = ids[idx + 1]
                    if idx > 0:
                        prev_id = ids[idx - 1]
                    if user is not None:
                        rows = await status_map(s, user, stage.course_id)
                        done = sum(1 for r in rows if r["status"] == STATUS_PASSED)
                        progress_pct = round(done / max(1, len(rows)) * 100)
                        prog = await get_progress(s, user.id, lesson_id)
                        passed_before = bool(prog and prog.status == STATUS_PASSED)
        except Exception as e:  # noqa: BLE001
            log.debug("تعذّر حساب التقدم: %s", e)

    header = lv.render_header(
        lesson.title,
        lesson.summary or "",
        difficulty=lesson.difficulty or "beginner",
        est_minutes=lesson.est_minutes or 20,
        lesson_number=lesson_no,
        total_lessons=total_lessons,
        progress_percent=progress_pct,
        day_number=lesson_no,
    )
    objectives = lv.render_objectives(lesson.objectives)
    pending: list[str] = [(header + objectives)[:3900]]

    if is_outline:
        if not settings.ai_configured:
            note = "🕓 هذا الدرس <b>مخطّط</b> — محتواه سيُولَّد تلقائيا عند تفعيل المساعد الذكي (AI)."
        else:
            note = (
                "🕓 <b>المحتوى قيد البناء الآن</b> — سيصلك الشرح الكامل والأمثلة والأسئلة "
                "هنا تلقائيا بعد لحظات (بلا حاجة لأي زر)."
            )
        pending.append(note)

    # ---------- المحتوى ----------
    if lesson.content_md:
        sections = lv.split_markdown_sections(lesson.content_md)
        for i, (title, body) in enumerate(sections.items(), start=1):
            if not body.strip():
                continue
            chunk = lv.render_section(title, lv.md_to_tg(body), index=i)
            pending.append(chunk)

    # ---------- نقاط المفتاح ----------
    key_points = lv.render_key_points(lesson.key_points or [])
    if key_points:
        pending.append(key_points[:3900])

    # ---------- خطّاف الذاكرة ----------
    hook = lv.render_memory_hook(lesson.memory_hook or "")
    if hook:
        pending.append(hook[:3900])

    # ---------- للتوسّع أكثر ----------
    extra = lv.render_further_reading(getattr(lesson, "further_reading", None))
    if extra:
        pending.append(extra[:3900])

    # ---------- الأكواد ----------
    if codes:
        await _flush_blocks(message, pending)
        await _send_code_blocks(message, codes)

    # ---------- التنبيهات ----------
    gotchas: list[str] = []
    sec_notes: list[str] = []
    for c in codes:
        gotchas.extend(c.gotchas or [])
        sec_notes.extend(c.security_notes or [])
    gotchas = list(dict.fromkeys(gotchas))[:6]
    sec_notes = list(dict.fromkeys(sec_notes))[:6]
    warn = lv.render_warnings(gotchas, sec_notes)
    if warn:
        pending.append(warn[:3900])

    # ---------- بطاقة المراجعة ----------
    review = lv.render_review_card(
        summary=lesson.summary or "",
        key_points=lesson.key_points or [],
        memory_hook=lesson.memory_hook or "",
        next_step=next_title,
    )
    if review:
        pending.append(review[:3900])

    await _flush_blocks(message, pending)
    await _send_assets(message, assets)

    # ---------- الأزرار ----------
    buttons: list[list[InlineKeyboardButton]] = []
    nav_row: list[InlineKeyboardButton] = []
    if prev_id:
        nav_row.append(
            InlineKeyboardButton("⬅️ السابق", callback_data=f"lesson:{prev_id}")
        )
    if next_id:
        nav_row.append(
            InlineKeyboardButton("التالي ➡️", callback_data=f"lesson:{next_id}")
        )
    if nav_row:
        buttons.append(nav_row)
    if is_outline:
        buttons.append(
            [
                InlineKeyboardButton("⚙️ توليد الآن", callback_data=f"gen:{lesson_id}"),
                InlineKeyboardButton("🔄 تحديث", callback_data=f"lesson:{lesson_id}"),
            ]
        )
    else:
        buttons.append(
            [
                InlineKeyboardButton(
                    "🔁 إعادة الاختبار" if passed_before else "🧠 بدء الاختبار",
                    callback_data=f"qz_start:{lesson_id}",
                ),
                InlineKeyboardButton("🧪 تمرين الكود", callback_data=f"exs:{lesson_id}"),
            ]
        )
    buttons.append(
        [InlineKeyboardButton("📎 ملحقات الدرس", callback_data=f"latt:{lesson_id}")]
    )
    if codes:
        buttons.insert(
            0,
            [InlineKeyboardButton(f"📚 موسوعة الأكواد ({len(codes)})", callback_data=f"codelist:{lesson_id}")],
        )
    if labs:
        buttons.append([InlineKeyboardButton(f"🧪 المختبرات ({len(labs)})", callback_data=f"lab_list:{lesson_id}")])
    buttons.append(
        [
            InlineKeyboardButton("🤖 اشرح الدرس", callback_data=f"aex:{lesson_id}"),
            InlineKeyboardButton("💬 نقاش", callback_data=f"qa:{lesson_id}"),
        ]
    )
    buttons.append(
        [
            InlineKeyboardButton("🎒 مركز التعلّم", callback_data="x:review"),
            InlineKeyboardButton("🔬 غوص عميق", callback_data="x:deep"),
        ]
    )
    await tg.send_text(
        message,
        "جاهز؟" if not is_outline else "المحتوى قيد البناء تلقائيا 👆",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def lesson_attachments(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يعرض كل اختيارات الدرس مجمّعة في زر واحد (ملحقات الدرس)."""
    q = update.callback_query
    await q.answer()
    lesson_id = int(q.data.split(":")[1])
    async with SessionLocal() as s:
        lesson = await s.get(Lesson, lesson_id)
        if not lesson:
            await q.message.reply_text("الدرس غير موجود.")
            return
        n_codes = int(
            await s.scalar(
                select(func.count()).select_from(CodeSample).where(CodeSample.lesson_id == lesson_id)
            )
            or 0
        )
        labs = await labs_for_lesson(s, lesson_id)
        n_assets = int(
            await s.scalar(
                select(func.count()).select_from(LessonAsset).where(LessonAsset.lesson_id == lesson_id)
            )
            or 0
        )
    ready = lesson.status != "outline" and bool(lesson.content_md)

    rows: list[list[InlineKeyboardButton]] = []
    if ready:
        rows.append(
            [
                InlineKeyboardButton("🧠 الاختبار", callback_data=f"qz_start:{lesson_id}"),
                InlineKeyboardButton("🧪 تمرين الكود", callback_data=f"exs:{lesson_id}"),
            ]
        )
    if n_codes:
        rows.append(
            [InlineKeyboardButton(f"📚 موسوعة الأكواد ({n_codes})", callback_data=f"codelist:{lesson_id}")]
        )
    if labs:
        rows.append([InlineKeyboardButton(f"🧪 المختبرات ({len(labs)})", callback_data=f"lab_list:{lesson_id}")])
    if n_assets:
        rows.append([InlineKeyboardButton("🎧 الوسائط المرفقة", callback_data=f"lass:{lesson_id}")])
    rows.append(
        [
            InlineKeyboardButton("🔖 حفظ", callback_data=f"bm:{lesson_id}"),
            InlineKeyboardButton("📝 ملاحظة", callback_data=f"note:{lesson_id}"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton("🤖 اشرح الدرس", callback_data=f"aex:{lesson_id}"),
            InlineKeyboardButton("💬 نقاش", callback_data=f"qa:{lesson_id}"),
        ]
    )
    rows.append([InlineKeyboardButton("📤 تصدير الدرس", callback_data=f"export:{lesson_id}")])
    rows.append([InlineKeyboardButton("⬅️ رجوع للدرس", callback_data=f"lesson:{lesson_id}")])
    await tg.send_text(
        q.message,
        f"📎 <b>ملحقات الدرس</b> — {lv.esc(lesson.title)}\n<i>كل ما تحتاجه لهذا الدرس في مكان واحد.</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def _auto_build_and_push(bot, chat_id: int, lesson_id: int) -> None:
    """يبني الدرس في الخلفية، ثم يدفع محتواه الكامل تلقائيا للمستخدم."""
    from pipeline import jobs

    base = (
        "⚡ <b>نبني هذا الدرس الآن…</b>\n"
        "<i>سيصلك الشرح الكامل والأمثلة والأسئلة هنا تلقائيا.</i>"
    )
    status = None
    try:
        status = await bot.send_message(
            chat_id, base, parse_mode=ParseMode.HTML, disable_web_page_preview=True
        )
    except Exception as e:  # noqa: BLE001
        log.debug("تعذّر إرسال رسالة البناء: %s", e)

    stop = asyncio.Event()
    ticker = (
        asyncio.create_task(animate_status(status, stop, base, note="نكتب الشرح والأمثلة والاختبار."))
        if status
        else None
    )
    try:
        res = await jobs.generate_lesson_now(lesson_id, fast=True, timeout=115)
    except Exception as e:  # noqa: BLE001
        log.exception("فشل بناء الدرس #%s: %s", lesson_id, e)
        res = {"ok": False, "error": str(e)[:200]}
    stop.set()
    if ticker is not None:
        ticker.cancel()
        try:
            await ticker
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass

    if res.get("ok"):
        if status is not None:
            try:
                await status.delete()
            except Exception:  # noqa: BLE001
                pass
        await _render_lesson(
            bot, chat_id, lesson_id, notice="✅ <b>الدرس جاهز</b> — إليك الشرح الكامل:"
        )
        _spawn(_prefetch_next(lesson_id))
        return

    log.warning("بناء الدرس #%s فشل/تأخر: %s", lesson_id, res.get("error"))
    try:
        async with SessionLocal() as s:
            await jobs.enqueue_lesson(s, lesson_id, priority=9)
    except Exception as e:  # noqa: BLE001
        log.warning("تعذّر إدراج توليد احتياطي: %s", e)
    problem = res.get("error") or "انتهت المهلة"
    heading = "⏳ <b>الخدمة مزدحمة قليلا</b>" if res.get("busy") else "⚠️ <b>تعذّر تجهيز الدرس الآن</b>"
    text = (
        f"{heading}\n"
        f"{ai_error_text(problem)}\n\n"
        "<i>أُدرج الدرس في قائمة التوليد التلقائي — سيصلك تلقائيا عند اكتماله.</i>"
    )
    if status is not None:
        try:
            await tg.edit_text(status, text, parse_mode=ParseMode.HTML)
        except Exception:  # noqa: BLE001
            pass
    _spawn(_push_when_ready(bot, chat_id, lesson_id))


async def _push_when_ready(
    bot, chat_id: int, lesson_id: int, *, tries: int = 30, delay: float = 10.0
) -> None:
    """يراقب الدرس في الخلفية ويدفعه للمستخدم فور اكتماله تلقائيا."""
    for _ in range(tries):
        await asyncio.sleep(delay)
        ready = False
        try:
            async with SessionLocal() as s:
                lesson = await s.get(Lesson, lesson_id)
                ready = bool(lesson and lesson.content_md and lesson.status != "outline")
        except Exception as e:  # noqa: BLE001
            log.debug("تعذّر فحص جهوزية الدرس #%s: %s", lesson_id, e)
        if ready:
            await _render_lesson(
                bot, chat_id, lesson_id, notice="✅ <b>الدرس جاهز</b> — إليك الشرح الكامل:"
            )
            return


async def _prefetch_next(lesson_id: int, n: int = 2) -> None:
    """يُحضّر الدرسين التاليين مسبقا كي يظهرا فورا عند فتحهما."""
    from pipeline import jobs

    try:
        from core.learning import ordered_lessons

        async with SessionLocal() as s:
            lesson = await s.get(Lesson, lesson_id)
            if not lesson:
                return
            stage = await s.get(Stage, lesson.stage_id)
            if not stage:
                return
            siblings = await ordered_lessons(s, stage.course_id)
            ids = [x.id for x in siblings]
            if lesson_id not in ids:
                return
            idx = ids.index(lesson_id)
            for nid in ids[idx + 1: idx + 1 + n]:
                nxt = await s.get(Lesson, nid)
                if nxt and (nxt.status == "outline" or not nxt.content_md):
                    await jobs.enqueue_lesson(s, nid, priority=4)
    except Exception as e:  # noqa: BLE001
        log.debug("تعذّر التحضير المسبق: %s", e)


async def _send_assets(message, assets: list[LessonAsset]) -> None:
    """يرسل وسائط الدرس (صوت/فيديو/صور) إن وُجدت."""
    for a in assets:
        try:
            if a.kind == "audio":
                await message.reply_audio(a.url)
            elif a.kind == "video":
                await message.reply_video(a.url)
            elif a.kind == "image":
                await message.reply_photo(a.url)
            elif a.kind == "pdf":
                await message.reply_document(a.url)
        except Exception as e:  # noqa: BLE001
            log.warning("تعذّر إرسال وسيط %s: %s", a.id, e)


async def lesson_assets(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يعرض وسائط/ملفات الدرس المرفقة."""
    q = update.callback_query
    await q.answer()
    lesson_id = int(q.data.split(":")[1])
    async with SessionLocal() as s:
        assets = list(
            (await s.execute(select(LessonAsset).where(LessonAsset.lesson_id == lesson_id))).scalars().all()
        )
    if not assets:
        await tg.send_text(q.message, "🎧 لا توجد وسائط مرفقة بهذا الدرس.")
        return
    await tg.send_text(q.message, f"🎧 <b>وسائط الدرس</b> ({len(assets)})", parse_mode=ParseMode.HTML)
    await _send_assets(q.message, assets)


async def generate_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """توليد درس مخطط فورا — متاح لكل المستخدمين بلا حدود زمنية."""
    q = update.callback_query
    lesson_id = int(q.data.split(":")[1])
    if not settings.ai_configured:
        await q.answer("AI غير مضبوط — تعذّر التوليد.", show_alert=True)
        return

    await q.answer("بدأ البناء — سيصلك الدرس تلقائيا بعد لحظات ⏳")
    _spawn(_auto_build_and_push(context.bot, update.effective_chat.id, lesson_id))


# ---------------------------------------------------------------------
#  الاختبار
# ---------------------------------------------------------------------
def _quiz_done_kb(
    lesson_id: int, next_id: int | None, *, passed: bool
) -> InlineKeyboardMarkup:
    """أزرار ما بعد الاختبار: التالي، إعادة، تمرين، الدرس."""
    rows: list[list[InlineKeyboardButton]] = []
    if passed and next_id:
        rows.append(
            [InlineKeyboardButton("➡️ الدرس التالي", callback_data=f"lesson:{next_id}")]
        )
    rows.append(
        [
            InlineKeyboardButton("🔁 إعادة الاختبار", callback_data=f"qz_start:{lesson_id}"),
            InlineKeyboardButton("🧪 تمرين الدرس", callback_data=f"exs:{lesson_id}"),
        ]
    )
    rows.append(
        [InlineKeyboardButton("📖 العودة للدرس", callback_data=f"lesson:{lesson_id}")]
    )
    return InlineKeyboardMarkup(rows)


async def _render_question(message, context: ContextTypes.DEFAULT_TYPE, show_feedback: bool = False) -> None:
    st = context.user_data["quiz"]
    qid = st["qids"][st["i"]]
    async with SessionLocal() as s:
        q = await s.get(Question, qid)
        opts = list(
            (await s.execute(
                select(Option).where(Option.question_id == qid).order_by(Option.order_index)
            )).scalars().all()
        )
    chosen = set(st["resp"].get(qid, []))
    correct_ids = {o.id for o in opts if o.is_correct}
    is_answered = qid in st["resp"]
    
    lines = [f"🧠 سؤال {st['i'] + 1} / {len(st['qids'])}", "", q.text, ""]
    
    # Show feedback if answered and show_feedback is True (after finishing quiz)
    if show_feedback and is_answered:
        chosen_correct = chosen & {o.id for o in opts if o.is_correct}
        if chosen == {o.id for o in opts if o.is_correct}:
            lines.append("✅ <b>إجابة صحيحة!</b>")
        else:
            lines.append("❌ <b>إجابة خاطئة.</b>")
            # Show correct answer(s)
            correct_opts = [o for o in opts if o.is_correct]
            if len(correct_opts) == 1:
                lines.append(f"✅ الإجابة الصحيحة: <b>{correct_opts[0].text}</b>")
            else:
                lines.append("✅ الإجابات الصحيحة:")
                for o in correct_opts:
                    lines.append(f"  • <b>{o.text}</b>")
            # Show explanation if available
            if q.explanation:
                lines.append(f"💡 الشرح: {q.explanation}")
    # Show explanation immediately after answering in normal mode (instant feedback)
    elif not show_feedback and is_answered and q.explanation:
        # Show explanation right after answering (instant feedback mode)
        lines.append(f"💡 الشرح: {q.explanation}")
    
    buttons: list[list[InlineKeyboardButton]] = []
    for o in opts:
        if show_feedback:
            # In review mode, show correct/incorrect markers
            if o.id in correct_ids:
                mark = "✅ "
            elif o.id in chosen:
                mark = "❌ "
            else:
                mark = "⭘ "
        else:
            # Normal quiz mode
            mark = "✅ " if o.id in chosen else ("◻️ " if q.kind == "multi" else "🔘 ")
        buttons.append([InlineKeyboardButton(mark + o.text[:50], callback_data=f"qopt:{qid}:{o.id}")])
    
    nav = []
    if st["i"] > 0:
        nav.append(InlineKeyboardButton("⬅️ السابق", callback_data="qprev"))
    if st["i"] < len(st["qids"]) - 1:
        nav.append(InlineKeyboardButton("التالي ➡️", callback_data="qnext"))
    else:
        if show_feedback:
            nav.append(
                InlineKeyboardButton(
                    "🔁 إعادة الاختبار",
                    callback_data=f"qz_start:{st['lesson_id']}",
                )
            )
        else:
            nav.append(InlineKeyboardButton("🏁 إنهاء", callback_data="qfinish"))
    buttons.append(nav)
    
    parse_mode = ParseMode.HTML if show_feedback else ParseMode.MARKDOWN
    await message.reply_text(
        "\n".join(lines)[:3900],
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=parse_mode,
    )


async def quiz_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    lesson_id = int(q.data.split(":")[1])
    async with SessionLocal() as s:
        from core.models import Quiz

        quiz = await s.scalar(select(Quiz).where(Quiz.lesson_id == lesson_id))
        if not quiz:
            await tg.edit_text(q, "لا يوجد اختبار لهذا الدرس.")
            return
        qids = list(
            (await s.execute(
                select(Question.id).where(Question.quiz_id == quiz.id).order_by(Question.order_index)
            )).scalars().all()
        )
    context.user_data["quiz"] = {"lesson_id": lesson_id, "qids": qids, "i": 0, "resp": {}}
    await tg.edit_text(q, "ابدأنا الاختبار 👇")
    await _render_question(update.effective_message, context)


async def quiz_option(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    st = context.user_data.get("quiz")
    if not st:
        await q.answer("انتهت الجلسة، أعد البدء.", show_alert=True)
        return
    await q.answer()
    _, qid, oid = q.data.split(":")
    qid, oid = int(qid), int(oid)
    async with SessionLocal() as s:
        question = await s.get(Question, qid)
    cur = set(st["resp"].get(qid, []))
    if question.kind == "multi":
        cur.symmetric_difference_update({oid})
    else:
        cur = {oid}
    st["resp"][qid] = list(cur)
    try:
        await q.delete_message()
    except Exception:
        pass
    await _render_question(update.effective_message, context)


async def quiz_nav(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    st = context.user_data.get("quiz")
    if not st:
        await q.answer("انتهت الجلسة.", show_alert=True)
        return
    await q.answer()
    if q.data == "qprev":
        st["i"] = max(0, st["i"] - 1)
    elif q.data == "qnext":
        st["i"] = min(len(st["qids"]) - 1, st["i"] + 1)
    try:
        await q.delete_message()
    except Exception:
        pass
    await _render_question(update.effective_message, context)


async def quiz_result(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """عرض ملخص النتيجة النهائية بعد مراجعة الإجابات."""
    q = update.callback_query
    await q.answer()
    st = context.user_data.get("quiz")
    if not st:
        await q.answer("انتهت الجلسة.", show_alert=True)
        return
    
    lesson_id = st["lesson_id"]
    responses = {int(k): v for k, v in st["resp"].items()}
    async with SessionLocal() as s:
        lesson = await s.get(Lesson, lesson_id)
        user = await _user(s, update.effective_user.id)
        if not user:
            await tg.edit_text(q, "سجّل دخولك أولا.")
            return
        result = await submit_quiz(s, user, lesson, responses)
        cert = None
        stage = await s.get(Stage, lesson.stage_id)
        if result.get("passed") and stage:
            from core.learning import maybe_certificate
            cert = await maybe_certificate(s, user, stage.course_id)
    
    try:
        await q.delete_message()
    except Exception:
        pass
    
    if not result.get("ok"):
        await tg.send_text(update.effective_message, f"⚠️ {result.get('error')}")
        return
    
    if result["passed"]:
        msg = (
            f"🎉 *أحسنت!* نجحت بنسبة {result['score']}%\n"
            f"⭐ +{result['xp']} نقطة · 🔥 سلسلة {user.streak_count} يوم"
        )
        if result.get("badges"):
            msg += "\n🏅 شارات جديدة: " + ", ".join(result["badges"])
        if cert:
            msg += f"\n🎓 شهادة إتمام الكورس: `{cert.code}`"
        await tg.send_text(update.effective_message, msg, parse_mode=ParseMode.MARKDOWN)
        await _after_quiz_pass(update, context, lesson)
    else:
        await tg.send_text(update.effective_message, 
            f"😅 نسبتك {result['score']}% — تحتاج {lesson.min_score}%. أعد المحاولة عبر /courses."
        )
    
    context.user_data.pop("quiz", None)


async def _after_quiz_pass(update: Update, context: ContextTypes.DEFAULT_TYPE, lesson: Lesson) -> None:
    """بعد الاجتياز: يفتح الدرس التالي تلقائيا (والتمرين متاح بزر مستقل)."""
    from core.learning import lesson_day, next_lesson_id

    chat_id = update.effective_chat.id
    async with SessionLocal() as s:
        nxt = await next_lesson_id(s, lesson)
        nxt_lesson = await s.get(Lesson, nxt) if nxt else None
        nxt_day = await lesson_day(s, nxt_lesson) if nxt_lesson else None
        user = await _user(s, update.effective_user.id) if update.effective_user else None
    if nxt and nxt_lesson:
        # _display_and_build يتولى العرض + البناء/التحضير المسبق في الخلفية.
        await _display_and_build(
            context.bot, chat_id, nxt, user=user,
            notice=(
                "✅ <b>أُنجز الدرس!</b> فتحنا لك الدرس التالي تلقائيا.\n"
                f"📅 اليوم {nxt_day or ''} — {lv.esc(nxt_lesson.title)}"
            ),
        )
    else:
        await tg.send_text(
            update.effective_message,
            "🎓 <b>أكملت كل دروس هذا المسار!</b> راجع دروسك أو ابدأ لغة جديدة.",
            parse_mode=ParseMode.HTML,
        )


async def quiz_finish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    st = context.user_data.get("quiz")
    if not st:
        return
    lesson_id = st["lesson_id"]
    responses = {int(k): v for k, v in st["resp"].items()}
    async with SessionLocal() as s:
        lesson = await s.get(Lesson, lesson_id)
        user = await _user(s, update.effective_user.id)
        if not user:
            await tg.edit_text(q, "سجّل دخولك أولا.")
            return
        result = await submit_quiz(s, user, lesson, responses)
        nxt_id = await next_lesson_id(s, lesson)
        # شهادة الإتمام
        cert = None
        stage = await s.get(Stage, lesson.stage_id)
        if result.get("passed") and stage:
            from core.learning import maybe_certificate

            cert = await maybe_certificate(s, user, stage.course_id)

    context.user_data.pop("quiz", None)
    try:
        await q.delete_message()
    except Exception:
        pass

    if not result.get("ok"):
        await tg.send_text(update.effective_message, f"⚠️ {result.get('error')}")
        return

    if result["passed"]:
        msg = f"🎉 *أحسنت!* نجحت بنسبة {result['score']}%\n"
        if result.get("xp"):
            msg += f"⭐ +{result['xp']} نقطة · 🔥 سلسلة {user.streak_count} يوم\n"
        else:
            msg += "🔁 إعادة ناجحة — لا نقاط إضافية لهذا الدرس.\n"
        if result.get("badges"):
            msg += "🏅 شارات جديدة: " + ", ".join(result["badges"]) + "\n"
        if cert:
            msg += f"🎓 شهادة إتمام الكورس: `{cert.code}`\n"
        if nxt_id:
            msg += "➡️ فتحنا لك الدرس التالي."
        await tg.send_text(
            update.effective_message,
            msg,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_quiz_done_kb(lesson_id, nxt_id, passed=True),
        )
        await _after_quiz_pass(update, context, lesson)
        return

    await tg.send_text(
        update.effective_message,
        f"😅 نسبتك {result['score']}% — تحتاج {lesson.min_score}%.\n"
        "يمكنك إعادة الاختبار الآن أو مراجعة الإجابات بالأسفل.",
        reply_markup=_quiz_done_kb(lesson_id, nxt_id, passed=False),
    )
    # مراجعة الإجابات بعد الفشل من السؤال الأول.
    context.user_data["quiz"] = st
    st["show_feedback"] = True
    st["i"] = 0
    await _render_question(update.effective_message, context, show_feedback=True)
    context.user_data.pop("quiz", None)


# ---------------------------------------------------------------------
#  موسوعة الأكواد
# ---------------------------------------------------------------------
def _atlas_chunks(c: CodeSample) -> list[str]:
    parts: list[str] = [
        f"📚 <b>{_esc(c.title)}</b> — <code>{_esc(c.language)}</code>",
        f"<pre>{_esc(c.code)}</pre>",
        f"<i>{_esc(c.explanation)}</i>",
    ]
    if c.anatomy:
        parts.append("\n<b>🔬 تشريح سطري</b>")
        for a in c.anatomy:
            parts.append(
                f"<code>{_esc(str(a.get('line', '')))}</code> {_esc(a.get('code', ''))} — {_esc(a.get('explain', ''))}"
            )
    if c.usages:
        parts.append(f"\n<b>🧰 الاستخدامات ({len(c.usages)})</b>")
        for j, u in enumerate(c.usages, start=1):
            block = [f"<b>{j}. {_esc(u.get('name', ''))}</b>"]
            if u.get("signature"):
                block.append(f"<pre>{_esc(u['signature'])}</pre>")
            if u.get("description"):
                block.append(_esc(u["description"]))
            if u.get("example"):
                block.append(f"<pre>{_esc(u['example'])}</pre>")
            if u.get("output"):
                block.append(f"↩️ <i>{_esc(u['output'])}</i>")
            parts.append("\n".join(block))
    if c.parameters:
        parts.append("\n<b>⚙️ المعاملات</b>")
        for p in c.parameters:
            req = " [إلزامي]" if p.get("required") else ""
            dflt = f" — الافتراضي {_esc(p.get('default'))}" if p.get("default") else ""
            parts.append(
                f"• <code>{_esc(p.get('name', ''))}</code> ({_esc(p.get('type', ''))}): {_esc(p.get('description', ''))}{dflt}{req}"
            )
    if c.returns:
        parts.append(f"\n<b>↩️ القيمة المُرجعة</b>\n{_esc(c.returns)}")
    if c.gotchas:
        parts.append("\n<b>⚠️ أخطاء شائعة</b>")
        parts.extend(f"• {_esc(g)}" for g in c.gotchas)
    if c.security_notes:
        parts.append("\n<b>🛡️ ملاحظات أمنية</b>")
        parts.extend(f"• {_esc(g)}" for g in c.security_notes)
    if c.related:
        parts.append("\n🔗 مرتبط: " + "، ".join(_esc(r) for r in c.related))

    chunks: list[str] = []
    buf = ""
    for p in parts:
        block = p + "\n"
        if len(buf) + len(block) > 3500:
            chunks.append(buf)
            buf = ""
        buf += block
    if buf:
        chunks.append(buf)
    return chunks


async def code_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    lesson_id = int(q.data.split(":")[1])
    async with SessionLocal() as s:
        codes = list(
            (await s.execute(
                select(CodeSample).where(CodeSample.lesson_id == lesson_id).order_by(CodeSample.order_index)
            )).scalars().all()
        )
    if not codes:
        await tg.send_text(update.effective_message, "لا توجد أكواد لهذا الدرس.")
        return
    rows = [
        [InlineKeyboardButton(f"{i}. {c.title[:45]}", callback_data=f"code:{c.id}")]
        for i, c in enumerate(codes, start=1)
    ]
    rows.append(
        [
            InlineKeyboardButton("🧠 اختبار الدرس", callback_data=f"qz_start:{lesson_id}"),
            InlineKeyboardButton("⬅️ رجوع للدرس", callback_data=f"lesson:{lesson_id}"),
        ]
    )
    # رسالة جديدة كي تبقى أزرار الدرس الأصلية (ومنها الاختبار) في مكانها.
    await update.effective_message.reply_text(
        f"📚 <b>موسوعة الأكواد ({len(codes)})</b>\n"
        "<i>اختر كودا لعرض تشريحه وكل استخداماته.</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def code_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    code_id = int(q.data.split(":")[1])
    async with SessionLocal() as s:
        c = await s.get(CodeSample, code_id)
    if not c:
        await tg.edit_text(q, "الكود غير موجود.")
        return
    try:
        await q.delete_message()
    except Exception:
        pass
    await _send_chunks(update.effective_message, _atlas_chunks(c))
    lesson_id = c.lesson_id
    await update.effective_message.reply_text(
        "🔎 ماذا بعد؟",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("▶️ شغّل هذا الكود", callback_data=f"runc:{c.id}"),
                    InlineKeyboardButton("📚 كل الأكواد", callback_data=f"codelist:{lesson_id}"),
                ],
                [
                    InlineKeyboardButton("🧠 اختبار الدرس", callback_data=f"qz_start:{lesson_id}"),
                    InlineKeyboardButton("⬅️ رجوع للدرس", callback_data=f"lesson:{lesson_id}"),
                ],
            ]
        ),
    )


def register_handlers(app) -> None:
    app.add_handler(CommandHandler("courses", courses_cmd))
    app.add_handler(CallbackQueryHandler(courses_page, pattern=r"^courses:\d+$"))
    app.add_handler(CallbackQueryHandler(course_callback, pattern=r"^course:\d+(:\d+)?$"))
    app.add_handler(CallbackQueryHandler(lesson_callback, pattern=r"^lesson:\d+$"))
    app.add_handler(CallbackQueryHandler(lesson_attachments, pattern=r"^latt:\d+$"))
    app.add_handler(CallbackQueryHandler(lesson_assets, pattern=r"^lass:\d+$"))
    app.add_handler(CallbackQueryHandler(generate_now, pattern=r"^gen:\d+$"))
    app.add_handler(CallbackQueryHandler(code_list, pattern=r"^codelist:\d+$"))
    app.add_handler(CallbackQueryHandler(code_detail, pattern=r"^code:\d+$"))
    app.add_handler(CallbackQueryHandler(run_code_sample, pattern=r"^runc:\d+$"))
    app.add_handler(CallbackQueryHandler(quiz_start, pattern=r"^qz_start:\d+$"))
    app.add_handler(CallbackQueryHandler(quiz_option, pattern=r"^qopt:\d+:\d+$"))
    app.add_handler(CallbackQueryHandler(quiz_nav, pattern=r"^q(next|prev)$"))
    app.add_handler(CallbackQueryHandler(quiz_finish, pattern=r"^qfinish$"))
    app.add_handler(CallbackQueryHandler(quiz_result, pattern=r"^qresult$"))

