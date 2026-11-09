# -*- coding: utf-8 -*-
"""معالجات الملف: الدرس اليومي، الصدارة، الملاحظات، المرجعيات، الشهادات."""
from __future__ import annotations

import html

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from sqlalchemy import select

from core.config import settings
from core.db import SessionLocal
from core.gamification import (
    add_note,
    list_bookmarks,
    list_notes,
    toggle_bookmark,
    user_rank,
    xp_leaderboard,
)
from core.learning import (
    STATUS_AVAILABLE,
    STATUS_IN_PROGRESS,
    STATUS_LOCKED,
    STATUS_PASSED,
    lesson_day,
    passed_today,
    selected_courses,
    status_map,
    todays_daily,
)
from core.logging import get_logger
from core.models import Certificate, Course, LearningPath, Lesson, Stage
from core.paths import get_path as get_learning_path
from core.paths import list_paths, path_progress
from core.repo import get_user_by_telegram
from app import tg

log = get_logger("bot.profile")

ASK_NOTE = 200


async def _user(session, tg_id):
    return await get_user_by_telegram(session, tg_id)


_PLAN_ICONS = {
    STATUS_PASSED: "✅",
    STATUS_IN_PROGRESS: "🔄",
    STATUS_AVAILABLE: "🔓",
    STATUS_LOCKED: "🔒",
}


async def _active_path(session, user) -> LearningPath | None:
    if not user or not user.active_path_slug:
        return None
    return await get_learning_path(session, user.active_path_slug)


async def _resolve_scope(session, user) -> tuple[list[Course], LearningPath | None]:
    """كورسات المستخدم المختارة + المسار، مع اختيار تلقائي لآخر كورس نشط."""
    path = await _active_path(session, user)
    courses = await selected_courses(session, user)
    if courses:
        return courses, path
    # اختيار تلقائي: كورس آخر درس فتحه المستخدم (حتى لا يبدأ من الصفر).
    from core.reminders import latest_progress

    prog = await latest_progress(session, user.id)
    if prog:
        lesson = await session.get(Lesson, prog.lesson_id)
        stage = await session.get(Stage, lesson.stage_id) if lesson else None
        if stage:
            user.active_course_id = stage.course_id
            await session.commit()
            course = await session.get(Course, stage.course_id)
            if course:
                return [course], None
    return [], None


async def _daily_picker(session, message, user) -> None:
    """يعرض المسارات (والكورسات) لاختيار وجهة الدرس اليومي."""
    paths = await list_paths(session)
    lines = [
        "🎯 <b>الدرس اليومي</b>",
        "",
        "اختر مسارك مرة واحدة، وسيصبح هذا المسار وجهة درسك اليومي "
        "وتذكيراتك — مع الدروس والاختبارات وكل الميزات.",
        "",
    ]
    buttons: list[list[InlineKeyboardButton]] = []
    for p in paths:
        d = await path_progress(session, user, p)
        icon = p.icon or "🛤️"
        lines.append(
            f"{icon} <b>{html.escape(p.title)}</b> — {d['percent']}% "
            f"({d['passed']}/{d['total']})"
        )
        buttons.append(
            [
                InlineKeyboardButton(
                    f"{icon} {p.title[:42]}", callback_data=f"dpath:{p.slug}"
                )
            ]
        )
    if paths:
        lines.append("")
        lines.append("<i>أو اختر كورساً مباشرة:</i>")

    res = await session.execute(
        select(Course)
        .where(Course.is_published.is_(True))
        .order_by(Course.order_index, Course.id)
    )
    courses = list(res.scalars().all())
    for c in courses[:8]:
        icon = c.icon or "📘"
        buttons.append(
            [
                InlineKeyboardButton(
                    f"{icon} {c.title[:42]}", callback_data=f"dcourse:{c.id}"
                )
            ]
        )
    if not paths and not courses:
        lines.append("لا توجد مسارات أو كورسات منشورة بعد.")
    await tg.send_text(
        message,
        "\n".join(lines)[:3900],
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def _send_daily(update: Update) -> None:
    """يبني بطاقة درس اليوم لمسار المستخدم مع كل الميزات."""
    message = update.effective_message
    tg_id = update.effective_user.id if update.effective_user else None
    async with SessionLocal() as s:
        user = await _user(s, tg_id) if tg_id else None
        if not user:
            await tg.send_text(message, "سجّل دخولك أولا عبر /start.")
            return
        courses, path = await _resolve_scope(s, user)
        if not courses:
            await _daily_picker(s, message, user)
            return

        lesson = await todays_daily(s, user)
        if not lesson:
            scope = f"مسار «{html.escape(path.title)}»" if path else "كورسك الحالي"
            await tg.send_text(
                message,
                f"🎉 <b>أكملت {scope} بالكامل!</b>\n\n"
                "اختر مساراً جديداً لمواصلة التعلّم وفتح دروس واختبارات جديدة:",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(
                    [
                        [InlineKeyboardButton("🛤️ اختر مساراً جديداً", callback_data="dpick")],
                        [
                            InlineKeyboardButton(
                                "📚 كل الكورسات", callback_data="courses:0"
                            )
                        ],
                    ]
                ),
            )
            return

        day = await lesson_day(s, lesson)
        done_today = await passed_today(s, user.id)
        if path:
            d = await path_progress(s, user, path)
            scope_line = (
                f"{path.icon or '🛤️'} <b>{html.escape(path.title)}</b> — "
                f"{d['percent']}% ({d['passed']}/{d['total']})"
            )
        else:
            from core.learning import course_progress_summary

            d = await course_progress_summary(s, user, courses[0].id)
            scope_line = (
                f"📘 <b>{html.escape(courses[0].title)}</b> — "
                f"{d['percent']}% ({d['passed']}/{d['total']})"
            )
        lesson_id = lesson.id
        title = html.escape(lesson.title)
        summary = html.escape((lesson.summary or "")[:220])

    head = "🎯 <b>درس اليوم</b>" + (f" — اليوم {day}" if day else "")
    lines = [
        head,
        scope_line,
        f"⚡ أنجزت اليوم <b>{done_today}</b> درساً — بلا حد أقصى، تابع بقدر ما تشاء.",
        "",
        f"📖 <b>{title}</b>",
    ]
    if summary:
        lines.append(summary)
    lines.append("")
    lines.append(
        f"<i>اجتز الاختبار بنسبة {settings.QUIZ_PASS_PERCENT}% ليُفتح الدرس التالي "
        "تلقائياً — يمكنك دراسة أكثر من 10 دروس يومياً.</i>"
    )
    buttons = [
        [InlineKeyboardButton("▶️ افتح الدرس الآن", callback_data=f"lesson:{lesson_id}")],
        [
            InlineKeyboardButton("🧠 الاختبار", callback_data=f"qz_start:{lesson_id}"),
            InlineKeyboardButton("🧪 تمرين", callback_data=f"exs:{lesson_id}"),
        ],
        [
            InlineKeyboardButton("🤖 اسأل عن الدرس", callback_data=f"askl:{lesson_id}"),
            InlineKeyboardButton("🎒 مركز التعلّم", callback_data="x:review"),
        ],
        [
            InlineKeyboardButton("📚 خطة دروسي (10+)", callback_data="dplan:0"),
            InlineKeyboardButton("🛤️ تغيير المسار", callback_data="dpick"),
        ],
    ]
    await tg.send_text(
        message,
        "\n".join(lines)[:3900],
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_daily(update)


async def daily_path(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يختار المستخدم مساراً كاملاً كوجهة للدرس اليومي."""
    q = update.callback_query
    slug = q.data.split(":", 1)[1]
    await q.answer("تم اختيار المسار ✅")
    async with SessionLocal() as s:
        user = await _user(s, update.effective_user.id)
        path = await get_learning_path(s, slug)
        if not user or not path:
            await tg.send_text(update.effective_message, "المسار غير متاح.")
            return
        user.active_path_slug = path.slug
        courses = await selected_courses(s, user)
        user.active_course_id = courses[0].id if courses else None
        await s.commit()
    await _send_daily(update)


async def daily_course(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يختار المستخدم كورساً واحداً كوجهة للدرس اليومي."""
    q = update.callback_query
    course_id = int(q.data.split(":", 1)[1])
    await q.answer("تم اختيار الكورس ✅")
    async with SessionLocal() as s:
        user = await _user(s, update.effective_user.id)
        course = await s.get(Course, course_id)
        if not user or not course:
            await tg.send_text(update.effective_message, "الكورس غير متاح.")
            return
        user.active_path_slug = None
        user.active_course_id = course.id
        await s.commit()
    await _send_daily(update)


async def daily_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    async with SessionLocal() as s:
        user = await _user(s, update.effective_user.id)
        if not user:
            await tg.send_text(update.effective_message, "سجّل دخولك أولا.")
            return
        await _daily_picker(s, update.effective_message, user)


async def daily_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    await _send_daily(update)


async def daily_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """خطة دروس المسار — 10 لكل صفحة، بلا حد يومي."""
    q = update.callback_query
    offset = int(q.data.split(":", 1)[1])
    await q.answer()
    async with SessionLocal() as s:
        user = await _user(s, update.effective_user.id)
        if not user:
            await tg.send_text(update.effective_message, "سجّل دخولك أولا.")
            return
        courses, path = await _resolve_scope(s, user)
        if not courses:
            await _daily_picker(s, update.effective_message, user)
            return
        rows: list[tuple[Course, dict]] = []
        for c in courses:
            for r in await status_map(s, user, c.id):
                rows.append((c, r))
        done_today = await passed_today(s, user.id)

    start = next(
        (i for i, (_c, r) in enumerate(rows) if r["status"] != STATUS_PASSED),
        len(rows),
    )
    page = rows[start + offset: start + offset + 10]
    scope = f" — {html.escape(path.title)}" if path else ""
    lines = [
        f"🗂️ <b>خطة دروسك</b>{scope}",
        f"⚡ أنجزت اليوم <b>{done_today}</b> درساً — يمكنك متابعة أكثر من 10 بلا حد.",
        "<i>اضغط أي درس متاح لفتحه فوراً (✅ سبق اجتيازه، 🔄 قيد التقدّم، 🔓 متاح، 🔒 مقفل).</i>",
        "",
    ]
    if not page:
        lines.append("لا توجد دروس متبقية في هذا النطاق.")
    buttons: list[list[InlineKeyboardButton]] = []
    for i, (_c, r) in enumerate(page, start=start + offset + 1):
        icon = _PLAN_ICONS.get(r["status"], "•")
        lines.append(f"{icon} {i}. {html.escape(r['lesson'].title)}")
        if r["status"] != STATUS_LOCKED:
            buttons.append(
                [
                    InlineKeyboardButton(
                        f"{icon} {r['lesson'].title[:42]}",
                        callback_data=f"lesson:{r['lesson'].id}",
                    )
                ]
            )
    nav: list[InlineKeyboardButton] = []
    if offset > 0:
        nav.append(
            InlineKeyboardButton("⬅️ السابق", callback_data=f"dplan:{max(0, offset - 10)}")
        )
    if start + offset + 10 < len(rows):
        nav.append(
            InlineKeyboardButton("التالي ➡️", callback_data=f"dplan:{offset + 10}")
        )
    if nav:
        buttons.append(nav)
    buttons.append(
        [
            InlineKeyboardButton("🎯 درس اليوم", callback_data="dhome"),
            InlineKeyboardButton("🛤️ تغيير المسار", callback_data="dpick"),
        ]
    )
    await tg.send_text(
        update.effective_message,
        "\n".join(lines)[:3900],
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def rank(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with SessionLocal() as s:
        user = await _user(s, update.effective_user.id)
        board = await xp_leaderboard(s, 10)
        my_rank = await user_rank(s, user) if user else None
    lines = ["🏆 *لوحة الصدارة*\n"]
    for r in board:
        lines.append(f"{r['rank']}. {r['name']} — {r['xp']} نقطة")
    if my_rank:
        lines.append(f"\n📍 ترتيبك: #{my_rank} ({user.xp} نقطة)")
    await tg.send_text(update.effective_message, "\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def notes_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with SessionLocal() as s:
        user = await _user(s, update.effective_user.id)
        if not user:
            await tg.send_text(update.effective_message, "سجّل دخولك أولا.")
            return
        rows = await list_notes(s, user.id, 15)
    if not rows:
        await tg.send_text(update.effective_message, "📝 لا توجد ملاحظات بعد. افتح درسا واضغط «ملاحظة».")
        return
    lines = ["📝 *ملاحظاتي*\n"]
    for n in rows:
        lines.append(f"• {n.text[:120]}")
    await tg.send_text(update.effective_message, "\n".join(lines)[:3900], parse_mode=ParseMode.MARKDOWN)


async def bookmarks_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with SessionLocal() as s:
        user = await _user(s, update.effective_user.id)
        if not user:
            await tg.send_text(update.effective_message, "سجّل دخولك أولا.")
            return
        rows = await list_bookmarks(s, user.id, 15)
    if not rows:
        await tg.send_text(update.effective_message, "🔖 لا توجد مرجعيات بعد.")
        return
    buttons = [[InlineKeyboardButton(f"🔖 {r['title']}", callback_data=f"lesson:{r['lesson_id']}")] for r in rows]
    await tg.send_text(update.effective_message, "🔖 *مرجعياتي*", parse_mode=ParseMode.MARKDOWN,
                                              reply_markup=InlineKeyboardMarkup(buttons))


async def certificates_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with SessionLocal() as s:
        user = await _user(s, update.effective_user.id)
        if not user:
            await tg.send_text(update.effective_message, "سجّل دخولك أولا.")
            return
        certs = list((await s.execute(
            select(Certificate).where(Certificate.user_id == user.id)
        )).scalars().all())
        courses = {
            c.id: c.title
            for c in (await s.execute(select(Course))).scalars().all()
        }
    if not certs:
        await tg.send_text(update.effective_message, "🎓 لا توجد شهادات بعد. أكمل كورسا كاملا.")
        return
    lines = ["🎓 *شهاداتي*\n"]
    for c in certs:
        lines.append(f"• {courses.get(c.course_id, 'كورس')} — `{c.code}`")
    await tg.send_text(update.effective_message, "\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def bookmark_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    lesson_id = int(q.data.split(":")[1])
    async with SessionLocal() as s:
        user = await _user(s, update.effective_user.id)
        if not user:
            await q.message.reply_text("سجّل دخولك أولا عبر /start.")
            return
        added = await toggle_bookmark(s, user.id, lesson_id)
    await q.message.reply_text("🔖 أُضيف إلى مرجعياتك." if added else "أُزيل من مرجعياتك.")


async def note_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    context.user_data["note_lesson"] = int(q.data.split(":")[1])
    await q.message.reply_text("📝 أرسل نص ملاحظتك (اكتب /cancel للإلغاء):")
    return ASK_NOTE


async def note_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lesson_id = context.user_data.pop("note_lesson", None)
    text = (update.message.text or "").strip()
    if not lesson_id or not text:
        await tg.send_text(update.message, "لا يمكن حفظ ملاحظة فارغة.")
        return ConversationHandler.END
    async with SessionLocal() as s:
        user = await _user(s, update.effective_user.id)
        if not user:
            await tg.send_text(update.message, "سجّل دخولك أولا عبر /start.")
            return ConversationHandler.END
        await add_note(s, user.id, lesson_id, text[:2000])
    await tg.send_text(update.message, "✅ حُفظت ملاحظتك.")
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("note_lesson", None)
    await tg.send_text(update.message, "تم الإلغاء.")
    return ConversationHandler.END


def notes_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(note_entry, pattern=r"^note:\d+$")],
        states={ASK_NOTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, note_save)]},
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
        per_message=True,
    )


def register_handlers(app) -> None:
    app.add_handler(CommandHandler("daily", daily))
    app.add_handler(CommandHandler("rank", rank))
    app.add_handler(CommandHandler("notes", notes_cmd))
    app.add_handler(CommandHandler("bookmarks", bookmarks_cmd))
    app.add_handler(CommandHandler("certificates", certificates_cmd))
    app.add_handler(CallbackQueryHandler(daily_path, pattern=r"^dpath:[\w\-]+$"))
    app.add_handler(CallbackQueryHandler(daily_course, pattern=r"^dcourse:\d+$"))
    app.add_handler(CallbackQueryHandler(daily_pick, pattern=r"^dpick$"))
    app.add_handler(CallbackQueryHandler(daily_home, pattern=r"^dhome$"))
    app.add_handler(CallbackQueryHandler(daily_plan, pattern=r"^dplan:\d+$"))
    app.add_handler(CallbackQueryHandler(bookmark_toggle, pattern=r"^bm:\d+$"))
