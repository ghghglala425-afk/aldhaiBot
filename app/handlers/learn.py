# -*- coding: utf-8 -*-
"""معالجات التعلّم: استعراض الكورسات والمراحل والدروس، وعرض الأكواد، وإجراء الاختبار."""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes
from sqlalchemy import select

from app import lesson_view as lv
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
    """يقسّم نص HTML طويل إلى رسائل آمنة."""
    if not text:
        return
    buf = ""
    for line in text.splitlines(keepends=True):
        if len(buf) + len(line) > limit:
            await message.reply_text(buf[:limit], parse_mode=ParseMode.HTML,
                                     disable_web_page_preview=True)
            buf = ""
        buf += line
    if buf.strip():
        await message.reply_text(buf[:limit], parse_mode=ParseMode.HTML,
                                 disable_web_page_preview=True)


async def _send_code_blocks(message, codes: list[CodeSample]) -> None:
    """يعرض الأكواد بترويسة ملوّنة لكل كتلة."""
    total = len(codes)
    for i, c in enumerate(codes, start=1):
        block = lv.render_code_block(c.code, c.language or "", i, total, c.title)
        await _send_html_chunks(message, block)
        if c.explanation:
            await message.reply_text(
                f"💬 <i>{lv.esc(c.explanation)}</i>",
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        if c.expected_output:
            await message.reply_text(
                f"📤 <b>الخرج المتوقع:</b>\n<pre>{lv.esc(c.expected_output)}</pre>",
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )


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


async def lesson_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    lesson_id = int(q.data.split(":")[1])
    is_outline = False
    assets: list[LessonAsset] = []
    progress_pct = None
    lesson_no = None
    total_lessons = None
    next_title = ""
    async with SessionLocal() as s:
        lesson = await s.get(Lesson, lesson_id)
        if not lesson:
            await tg.edit_text(q, "الدرس غير موجود.")
            return
        user = await _user(s, update.effective_user.id)
        if not user:
            await tg.edit_text(q, "سجّل دخولك أولا عبر /start.")
            return
        # التحقق من فتح الدرس (الفتح المتسلسل)
        from core.learning import is_unlocked, ordered_lessons

        if not await is_unlocked(s, user, lesson):
            await tg.edit_text(q, 
                "🔒 هذا الدرس مقفل. يجب إكمال الدرس السابق أولاً.",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        is_outline = lesson.status == "outline" or not lesson.content_md

        # ---------- رقم الدرس + التقدم + الدرس التالي ----------
        try:
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
                    rows = await status_map(s, user, stage.course_id)
                    done = sum(1 for r in rows if r["status"] == STATUS_PASSED)
                    progress_pct = round(done / max(1, len(rows)) * 100)
        except Exception as e:  # noqa: BLE001
            log.debug("تعذّر حساب التقدم: %s", e)

        # ---------- تسجيل بدء التعلّم ----------
        try:
            await start_lesson(s, user.id, lesson_id)
        except Exception as e:  # noqa: BLE001
            log.warning("تعذّر تسجيل بدء الدرس: %s", e)

    # ---------- التوليد الفوري عند الفتح (Lazy fill سريع) ----------
    if is_outline and settings.GEN_LAZY_ON_OPEN and settings.ai_configured:
        status_msg = None
        try:
            status_msg = await update.effective_message.reply_text(
                "⚡ <b>نبني هذا الدرس الآن</b>\n"
                "<i>شرح عميق، أمثلة عملية، وأسئلة — خلال لحظات.</i>",
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception as e:  # noqa: BLE001
            log.debug("تعذّر إرسال رسالة التوليد: %s", e)

        from pipeline import jobs

        res = await jobs.generate_lesson_now(lesson_id, fast=True, timeout=150)
        if status_msg is not None:
            try:
                await status_msg.delete()
            except Exception:  # noqa: BLE001
                pass
        if not res.get("ok"):
            log.warning("توليد الدرس #%s فشل/تأخر: %s", lesson_id, res.get("error"))
            try:
                async with SessionLocal() as s:
                    await jobs.enqueue_lesson(s, lesson_id, priority=9)
            except Exception as e:  # noqa: BLE001
                log.warning("تعذّر إدراج توليد احتياطي: %s", e)

    # إعادة تحميل الدرس والأكواد بعد التوليد
    async with SessionLocal() as s:
        lesson = await s.get(Lesson, lesson_id) or lesson
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

    # ---------- الترويسة ----------
    header = lv.render_header(
        lesson.title,
        lesson.summary or "",
        difficulty=lesson.difficulty or "beginner",
        est_minutes=lesson.est_minutes or 20,
        lesson_number=lesson_no,
        total_lessons=total_lessons,
        progress_percent=progress_pct,
    )
    objectives = lv.render_objectives(lesson.objectives)
    await tg.send_text(update.effective_message, 
        (header + objectives)[:3900], parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )

    if is_outline:
        if not settings.ai_configured:
            note = "🕓 هذا الدرس <b>مخطّط</b> — محتواه سيُولَّد تلقائيا عند تفعيل المساعد الذكي (AI)."
        else:
            note = "🕓 هذا الدرس <b>مخطّط</b> — المحتوى قيد التوليد في الخلفية. اضغط «🔄 تحديث» بعد قليل."
        await tg.send_text(update.effective_message, note, parse_mode=ParseMode.HTML)

    # ---------- المحتوى ----------
    if lesson.content_md:
        sections = lv.split_markdown_sections(lesson.content_md)
        for i, (title, body) in enumerate(sections.items(), start=1):
            if not body.strip():
                continue
            chunk = lv.render_section(title, lv.md_to_tg(body), index=i)
            await _send_html_chunks(update.effective_message, chunk)

    # ---------- نقاط المفتاح ----------
    key_points = lv.render_key_points(lesson.key_points or [])
    if key_points:
        await tg.send_text(update.effective_message, key_points[:3900], parse_mode=ParseMode.HTML)

    # ---------- خطّاف الذاكرة ----------
    hook = lv.render_memory_hook(lesson.memory_hook or "")
    if hook:
        await tg.send_text(update.effective_message, hook[:3900], parse_mode=ParseMode.HTML)

    # ---------- للتوسّع أكثر ----------
    extra = lv.render_further_reading(getattr(lesson, "further_reading", None))
    if extra:
        await tg.send_text(update.effective_message, extra[:3900], parse_mode=ParseMode.HTML)

    # ---------- الأكواد ----------
    if codes:
        await _send_code_blocks(update.effective_message, codes)

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
        await tg.send_text(update.effective_message, warn[:3900], parse_mode=ParseMode.HTML)

    # ---------- بطاقة المراجعة ----------
    review = lv.render_review_card(
        summary=lesson.summary or "",
        key_points=lesson.key_points or [],
        memory_hook=lesson.memory_hook or "",
        next_step=next_title,
    )
    if review:
        await tg.send_text(update.effective_message, review[:3900], parse_mode=ParseMode.HTML)

    await _send_assets(update.effective_message, assets)

    # ---------- الأزرار ----------
    buttons: list[list[InlineKeyboardButton]] = []
    if is_outline:
        buttons.append(
            [
                InlineKeyboardButton("⚙️ توليد الآن", callback_data=f"gen:{lesson_id}"),
                InlineKeyboardButton("🔄 تحديث", callback_data=f"lesson:{lesson_id}"),
            ]
        )
    else:
        buttons.append([InlineKeyboardButton("🧠 بدء الاختبار", callback_data=f"qz_start:{lesson_id}")])
    if codes:
        buttons.insert(
            0,
            [InlineKeyboardButton(f"📚 موسوعة الأكواد ({len(codes)})", callback_data=f"codelist:{lesson_id}")],
        )
    if labs:
        buttons.append([InlineKeyboardButton(f"🧪 المختبرات ({len(labs)})", callback_data=f"lab_list:{lesson_id}")])
    buttons.append(
        [
            InlineKeyboardButton("🔖 حفظ", callback_data=f"bm:{lesson_id}"),
            InlineKeyboardButton("📝 ملاحظة", callback_data=f"note:{lesson_id}"),
        ]
    )
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
    buttons.append([InlineKeyboardButton("📤 تصدير الدرس", callback_data=f"export:{lesson_id}")])
    await tg.send_text(update.effective_message, 
        "جاهز؟" if not is_outline else "الدرس مخطط حاليا 👆",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


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


async def generate_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """توليد درس مخطط فورا — متاح لكل المستخدمين بلا حدود زمنية."""
    q = update.callback_query
    lesson_id = int(q.data.split(":")[1])
    if not settings.ai_configured:
        await q.answer("AI غير مضبوط — تعذّر التوليد.", show_alert=True)
        return

    from pipeline import jobs

    async with SessionLocal() as s:
        job = await jobs.enqueue_lesson(s, lesson_id, priority=9)
    await q.answer(
        "أُدرج التوليد — اضغط «تحديث» بعد قليل ⏳" if job else "التوليد قيد التنفيذ بالفعل ⏳",
        show_alert=True,
    )
    context.user_data["auto_refresh"] = lesson_id


# ---------------------------------------------------------------------
#  الاختبار
# ---------------------------------------------------------------------
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
            nav.append(InlineKeyboardButton("📊 عرض النتيجة", callback_data="qresult"))
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
    else:
        await tg.send_text(update.effective_message, 
            f"😅 نسبتك {result['score']}% — تحتاج {lesson.min_score}%. أعد المحاولة عبر /courses."
        )
    
    context.user_data.pop("quiz", None)


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
        msg = (
            f"🎉 *أحسنت!* نجحت بنسبة {result['score']}%\n"
            f"⭐ +{result['xp']} نقطة · 🔥 سلسلة {user.streak_count} يوم"
        )
        if result.get("badges"):
            msg += "\n🏅 شارات جديدة: " + ", ".join(result["badges"])
        if cert:
            msg += f"\n🎓 شهادة إتمام الكورس: `{cert.code}`"
        await tg.send_text(update.effective_message, msg, parse_mode=ParseMode.MARKDOWN)
    else:
        await tg.send_text(update.effective_message, 
            f"😅 نسبتك {result['score']}% — تحتاج {lesson.min_score}%. أعد المحاولة عبر /courses."
        )
    
    # Show detailed review with correct/incorrect answers
    st["show_feedback"] = True
    await _render_question(update.effective_message, context, show_feedback=True)


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
        await tg.edit_text(q, "لا توجد أكواد لهذا الدرس.")
        return
    rows = [
        [InlineKeyboardButton(f"{i}. {c.title[:45]}", callback_data=f"code:{c.id}")]
        for i, c in enumerate(codes, start=1)
    ]
    await tg.edit_text(q, 
        f"📚 موسوعة الأكواد ({len(codes)}) — اختر كودا لعرض تشريحه وكل استخداماته:",
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


def register_handlers(app) -> None:
    app.add_handler(CommandHandler("courses", courses_cmd))
    app.add_handler(CallbackQueryHandler(courses_page, pattern=r"^courses:\d+$"))
    app.add_handler(CallbackQueryHandler(course_callback, pattern=r"^course:\d+(:\d+)?$"))
    app.add_handler(CallbackQueryHandler(lesson_callback, pattern=r"^lesson:\d+$"))
    app.add_handler(CallbackQueryHandler(generate_now, pattern=r"^gen:\d+$"))
    app.add_handler(CallbackQueryHandler(code_list, pattern=r"^codelist:\d+$"))
    app.add_handler(CallbackQueryHandler(code_detail, pattern=r"^code:\d+$"))
    app.add_handler(CallbackQueryHandler(quiz_start, pattern=r"^qz_start:\d+$"))
    app.add_handler(CallbackQueryHandler(quiz_option, pattern=r"^qopt:\d+:\d+$"))
    app.add_handler(CallbackQueryHandler(quiz_nav, pattern=r"^q(next|prev)$"))
    app.add_handler(CallbackQueryHandler(quiz_finish, pattern=r"^qfinish$"))
    app.add_handler(CallbackQueryHandler(quiz_result, pattern=r"^qresult$"))

