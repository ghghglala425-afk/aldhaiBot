# -*- coding: utf-8 -*-
"""معالجات الميزات المتقدمة: المراجعة، البطاقات، الغوص العميق، الخطة، التحدي.

كل الأزرار تبدأ بـ `x:` لتفادي التعارض مع بقية المعالجات.
"""
from __future__ import annotations

import random

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes
from sqlalchemy import select

from app import lesson_view as lv
from core.db import SessionLocal
from core.learning import get_progress
from core.logging import get_logger
from core.models import Lesson, User
from core.repo import get_user_by_telegram

log = get_logger("bot.tools2")


async def _user(session, tg_id: int):
    return await get_user_by_telegram(session, tg_id)


# =============================================================================
#  لوحة الأدوات التعليمية
# =============================================================================
async def study_hub(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """لوحة مركزية للأدوات التعليمية."""
    tg_id = update.effective_user.id
    async with SessionLocal() as s:
        user = await _user(s, tg_id)
        if not user:
            await update.message.reply_text("سجّل دخولك أولا عبر /start.")
            return
        from core.learn_features import due_reviews, study_statistics

        stats = await study_statistics(s, user.id)
        due = await due_reviews(s, user.id, limit=5)

    lines = [
        "━━━━━━━━━━━━━━━━━━━━━",
        "🎒 <b>مركز التعلّم</b>",
        "━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"⭐ النقاط: <b>{user.xp}</b> · 📊 المستوى: <b>{user.level}</b>",
        f"✅ الدروس المكتملة: <b>{stats['lessons_done']}</b>",
        f"🎯 نسبة النجاح في الاختبارات: <b>{stats['success_rate']}%</b>",
        f"📝 المحاولات: <b>{stats['attempts']}</b> · 💻 تنفيذات الكود: <b>{stats['executions']}</b>",
    ]
    if due:
        lines += ["", f"🔁 <b>مراجعات مستحقة ({len(due)}):</b>"]
        for d in due[:5]:
            lines.append(f"  ▫️ {lv.esc(d['lesson'].title)}")
    else:
        lines += ["", "✅ لا توجد مراجعات مستحقة الآن."]

    kb = [
        [InlineKeyboardButton("🔁 المراجعة المتباعدة", callback_data="x:review"),
         InlineKeyboardButton("🃏 بطاقات المراجعة", callback_data="x:cards")],
        [InlineKeyboardButton("🔬 غوص عميق", callback_data="x:deep"),
         InlineKeyboardButton("🎲 تحدّي اليوم", callback_data="x:challenge")],
        [InlineKeyboardButton("📅 خطّطتي الأسبوعية", callback_data="x:plan"),
         InlineKeyboardButton("💪 نقاط قوتي", callback_data="x:skills")],
    ]
    await update.message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb)
    )


# =============================================================================
#  المراجعة المتباعدة
# =============================================================================
async def review_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    tg_id = update.effective_user.id
    async with SessionLocal() as s:
        user = await _user(s, tg_id)
        if not user:
            await q.edit_message_text("سجّل دخولك أولا.")
            return
        from core.learn_features import due_reviews

        due = await due_reviews(s, user.id, limit=5)

    if not due:
        await q.edit_message_text(
            "✅ لا توجد مراجعات مستحقة الآن. تعلّم دروسا جديدة وستعود للمراجعة تلقائيا.",
            parse_mode=ParseMode.HTML,
        )
        return

    context.user_data["review"] = {"items": [d["lesson"].id for d in due], "i": 0}
    await q.edit_message_text("🔁 <b>المراجعة المتباعدة</b>\nاختر درسا للمراجعة:", parse_mode=ParseMode.HTML)
    rows = [
        [InlineKeyboardButton(f"{i+1}. {lv.esc(d['lesson'].title[:34])}", callback_data=f"x:rv:{d['lesson'].id}")]
        for i, d in enumerate(due)
    ]
    await update.effective_message.reply_text(
        "👇 اختر:", reply_markup=InlineKeyboardMarkup(rows)
    )


async def review_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """يبدأ اختبار مراجعة سريعة لدرس."""
    q = update.callback_query
    await q.answer()
    lesson_id = int(q.data.split(":")[2])
    tg_id = update.effective_user.id
    async with SessionLocal() as s:
        user = await _user(s, tg_id)
        if not user:
            await q.edit_message_text("سجّل دخولك أولا.")
            return
        from core.learn_features import build_flashcards

        cards = await build_flashcards(s, lesson_id, limit=10)

    if not cards:
        await q.edit_message_text("لا توجد أسئلة مراجعة لهذا الدرس.")
        return
    context.user_data["flash"] = {"cards": cards, "i": 0, "revealed": False, "lesson_id": lesson_id}
    await _render_card(update, context)


async def _render_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    st = context.user_data["flash"]
    card = st["cards"][st["i"]]
    text = lv.render_flashcard(card, st["i"] + 1, len(st["cards"]), st.get("revealed", False))
    kb = []
    if not st.get("revealed"):
        kb.append([InlineKeyboardButton("👁️ اكشف الجواب", callback_data="x:reveal")])
    else:
        kb.append([
            InlineKeyboardButton("✅ عرفته", callback_data="x:know:5"),
            InlineKeyboardButton("🤔 جزئيا", callback_data="x:know:3"),
            InlineKeyboardButton("❌ نسيته", callback_data="x:know:0"),
        ])
    if st["i"] > 0:
        kb.append([InlineKeyboardButton("⬅️ السابقة", callback_data="x:cardprev")])
    await update.effective_message.reply_text(
        text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(kb)
    )


async def card_reveal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    st = context.user_data.get("flash")
    if not st:
        await q.edit_message_text("انتهت الجلسة.")
        return
    st["revealed"] = True
    await _render_card(update, context)


async def card_prev(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    st = context.user_data.get("flash")
    if not st:
        await q.edit_message_text("انتهت الجلسة.")
        return
    st["i"] = max(0, st["i"] - 1)
    st["revealed"] = False
    await _render_card(update, context)


async def card_next(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    st = context.user_data.get("flash")
    if not st:
        await q.edit_message_text("انتهت الجلسة.")
        return
    if st["i"] + 1 < len(st["cards"]):
        st["i"] += 1
        st["revealed"] = False
        await _render_card(update, context)
    else:
        await q.edit_message_text("✅ انتهت بطاقات المراجعة.", parse_mode=ParseMode.HTML)
        context.user_data.pop("flash", None)


async def card_rate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """تقييم الاسترجاع → يجدول المراجعة القادمة."""
    q = update.callback_query
    await q.answer()
    st = context.user_data.get("flash")
    if not st:
        await q.edit_message_text("انتهت الجلسة.")
        return
    quality = int(q.data.split(":")[3])
    tg_id = update.effective_user.id
    async with SessionLocal() as s:
        user = await _user(s, tg_id)
        if user:
            from core.learn_features import schedule_review

            res = await schedule_review(s, user.id, st["lesson_id"], quality)
            nxt = res.get("next_review", "")
            interval = res.get("interval", 1)
    context.user_data.pop("flash", None)
    await q.edit_message_text(
        f"✅ سُجّل تقييمك. المراجعة القادمة بعد <b>{interval}</b> يوم ({lv.esc(nxt)}).",
        parse_mode=ParseMode.HTML,
    )


# =============================================================================
#  الغوص العميق
# =============================================================================
async def deep_dive(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    tg_id = update.effective_user.id
    async with SessionLocal() as s:
        user = await _user(s, tg_id)
        if not user:
            await q.edit_message_text("سجّل دخولك أولا.")
            return
        from core.learning import ordered_lessons, status_map
        from core.models import Course

        courses = list((await s.execute(select(Course).where(Course.is_published.is_(True)))).scalars().all())
        candidates = []
        for course in courses:
            rows = await status_map(s, user, course.id)
            for r in rows:
                if r["status"] == "passed":
                    candidates.append(r["lesson"])
        if not candidates:
            await q.edit_message_text("🕓 أكمل درسا أولا ثم استعمل الغوص العميق.")
            return
        lesson = random.choice(candidates)

    kb = [
        [
            InlineKeyboardButton("⚡ سريع", callback_data=f"x:deep:{lesson.id}:quick"),
            InlineKeyboardButton("📘 عادي", callback_data=f"x:deep:{lesson.id}:standard"),
            InlineKeyboardButton("🔬 عميق", callback_data=f"x:deep:{lesson.id}:deep"),
        ]
    ]
    await q.edit_message_text(
        f"🔬 <b>الغوص العميق</b>\nاختر مستوى الشرح لدرس <b>{lv.esc(lesson.title)}</b>:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def deep_dive_show(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    _, _, lesson_id, level = q.data.split(":")
    async with SessionLocal() as s:
        from core.learn_features import deep_dive

        res = await deep_dive(s, int(lesson_id), level)
    if not res.get("ok"):
        await q.edit_message_text(res.get("error", "خطأ"))
        return
    text = f"━━━━━━━━━━━━━━━━━━━━━\n{res['title']}\n━━━━━━━━━━━━━━━━━━━━━\n\n{res['body']}"
    await update.effective_message.reply_text(
        text[:3900], parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )


# =============================================================================
#  تحدّي اليوم
# =============================================================================
async def challenge_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    tg_id = update.effective_user.id
    async with SessionLocal() as s:
        user = await _user(s, tg_id)
        if not user:
            await q.edit_message_text("سجّل دخولك أولا.")
            return
        from core.learn_features import daily_challenge

        ch = await daily_challenge(s, user.id)

    if not ch.get("ok"):
        await q.edit_message_text(f"🎲 {ch.get('error')}")
        return
    context.user_data["challenge"] = ch
    opts = ch["options"]
    kb = [
        [InlineKeyboardButton(("✅ " if o["correct"] else "") + lv.esc(o["text"][:40]),
                              callback_data=f"x:chans:{ch['question_id']}:{o['id']}")]
        for o in opts
    ]
    await q.edit_message_text(
        f"🎲 <b>تحدّي اليوم</b>\n📚 {lv.esc(ch['lesson_title'])}\n\n❓ {lv.esc(ch['text'])}",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(kb),
    )


async def challenge_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    ch = context.user_data.get("challenge")
    if not ch:
        await q.edit_message_text("انتهى التحدي.")
        return
    _, _, qid, oid = q.data.split(":")
    chosen = int(oid)
    correct_id = next((o["id"] for o in ch["options"] if o["correct"]), None)
    ok = chosen == correct_id
    correct_text = next((o["text"] for o in ch["options"] if o["correct"]), "")
    icon = "✅" if ok else "❌"
    msg = f"{icon} <b>{'إجابة صحيحة!' if ok else 'إجابة خاطئة.'}</b>"
    if not ok:
        msg += f"\n✅ الصحيحة: {lv.esc(correct_text)}"
    await q.edit_message_text(msg, parse_mode=ParseMode.HTML)
    context.user_data.pop("challenge", None)


# =============================================================================
#  الخطة الأسبوعية + نقاط القوة
# =============================================================================
async def weekly_plan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    tg_id = update.effective_user.id
    async with SessionLocal() as s:
        user = await _user(s, tg_id)
        if not user:
            await q.edit_message_text("سجّل دخولك أولا.")
            return
        from core.learn_features import weekly_plan

        plan = await weekly_plan(s, user.id, days=7)

    days_ar = ["الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
    lines = ["━━━━━━━━━━━━━━━━━━━━━", "📅 <b>خطّطتي الأسبوعية</b>", "━━━━━━━━━━━━━━━━━━━━━"]
    total_min = 0
    for item in plan:
        lines.append("")
        lines.append(f"{days_ar[(item['day'] - 1) % 7]} — <b>{len(item['lessons'])}</b> درس")
        for lsn in item["lessons"]:
            total_min += lsn["minutes"]
            lines.append(f"  ▫️ {lv.esc(lsn['title'][:46])} <i>({lsn['minutes']} د)</i>")
    if total_min:
        lines += ["", f"⏱️ الإجمالي: <b>{total_min}</b> دقيقة (~{total_min // 60} ساعة)"]
    await q.edit_message_text("\n".join(lines)[:3900], parse_mode=ParseMode.HTML)


async def skills_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    tg_id = update.effective_user.id
    async with SessionLocal() as s:
        user = await _user(s, tg_id)
        if not user:
            await q.edit_message_text("سجّل دخولك أولا.")
            return
        from core.learn_features import skill_breakdown

        res = await skill_breakdown(s, user.id)

    if not res.get("ok"):
        await q.edit_message_text(f"💪 {res.get('error')}")
        return
    lines = [
        "━━━━━━━━━━━━━━━━━━━━━",
        "💪 <b>تحليل الأداء</b>",
        "━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"📊 متوسط درجاتك: <b>{res['average']}%</b>",
        f"🟢 دروس قوية: <b>{res['strong_count']}</b> · 🔴 تحتاج مراجعة: <b>{res['weak_count']}</b>",
    ]
    if res.get("weak_lessons"):
        lines += ["", "🔁 <b>راجع هذه الدروس:</b>"]
        for w in res["weak_lessons"]:
            lines.append(f"  ▫️ {lv.esc(w['title'])} <i>({w['score']}%)</i>")
    await q.edit_message_text("\n".join(lines)[:3900], parse_mode=ParseMode.HTML)


# =============================================================================
#  تسجيل استقبال
# =============================================================================
def register_handlers(app) -> None:
    app.add_handler(CommandHandler("hub", study_hub))
    app.add_handler(CallbackQueryHandler(review_start, pattern=r"^x:review$"))
    app.add_handler(CallbackQueryHandler(review_quiz, pattern=r"^x:rv:\d+$"))
    app.add_handler(CallbackQueryHandler(card_reveal, pattern=r"^x:reveal$"))
    app.add_handler(CallbackQueryHandler(card_prev, pattern=r"^x:cardprev$"))
    app.add_handler(CallbackQueryHandler(card_next, pattern=r"^x:cardnext$"))
    app.add_handler(CallbackQueryHandler(card_rate, pattern=r"^x:know:\d$"))
    app.add_handler(CallbackQueryHandler(deep_dive, pattern=r"^x:deep$"))
    app.add_handler(CallbackQueryHandler(deep_dive_show, pattern=r"^x:deep:\d+:(quick|standard|deep)$"))
    app.add_handler(CallbackQueryHandler(challenge_start, pattern=r"^x:challenge$"))
    app.add_handler(CallbackQueryHandler(challenge_answer, pattern=r"^x:chans:\d+:\d+$"))
    app.add_handler(CallbackQueryHandler(weekly_plan_cmd, pattern=r"^x:plan$"))
    app.add_handler(CallbackQueryHandler(skills_cmd, pattern=r"^x:skills$"))
