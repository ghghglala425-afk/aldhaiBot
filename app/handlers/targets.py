# -*- coding: utf-8 -*-
"""معالجات بيئات الهدف (Targets): تشغيل/إيقاف الحاوية، وعرض المهام وتسليمها."""
from __future__ import annotations

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

from core import targets as svc
from core.db import SessionLocal
from core.logging import get_logger
from core.models import Lab
from core.repo import get_user_by_telegram
from app import tg

log = get_logger("bot.targets")

AWAIT_ANSWER = 300


async def _render(update: Update, context: ContextTypes.DEFAULT_TYPE, lab_id: int, new: bool) -> None:
    async with SessionLocal() as s:
        lab = await s.get(Lab, lab_id)
        user = await get_user_by_telegram(s, update.effective_user.id)
        if not lab:
            await tg.send_text(update.effective_message, "بيئة الهدف غير موجودة.")
            return
        st = await svc.status(s, user, lab)
        ts = await svc.task_state(s, user, lab)

    mode = st.get("mode", "docker")
    if mode == "external":
        status_line = "🌐 هدف خارجي (جاهز)"
    elif mode == "guided":
        status_line = "📖 نمط موجّه (بدون تشغيل حاوية)"
    else:
        status_line = "🟢 تعمل" if st["status"] == "running" else "🔴 متوقفة"

    lines: list[str] = [
        f"🎯 *{lab.title}*",
        lab.description or "",
        "",
        f"📟 الحالة: {status_line}",
        f"✅ المهام: {ts['earned']}/{ts['total_points']} نقطة ({ts['percent']}%)",
    ]
    if mode == "docker":
        lines.insert(4, f"🐳 الصورة: `{lab.docker_image}`")
    if st.get("url"):
        lines.insert(4, f"🔗 الرابط: {st['url']}")

    rows: list[list[InlineKeyboardButton]] = []
    if mode == "external":
        rows.append([InlineKeyboardButton("🌐 فتح الهدف", url=st["url"])])
    elif mode == "guided":
        lines.insert(4, "ℹ️ شغّل الهدف بنفسك عبر Docker (`docker run` للصورة أعلاه) أو اضبط هدفا خارجيا، وتابع حلّ المهام هنا.")
        if lab.external_url:
            rows.append([InlineKeyboardButton("🌐 الهدف الخارجي", url=lab.external_url)])
    elif st["status"] == "running":
        rows.append([InlineKeyboardButton("⏹️ إيقاف البيئة", callback_data=f"tstop:{lab_id}")])
    else:
        rows.append([InlineKeyboardButton("▶️ تشغيل البيئة", callback_data=f"tstart:{lab_id}")])
    for t in ts["tasks"]:
        mark = "✅" if t["solved"] else "🔲"
        rows.append([InlineKeyboardButton(
            f"{mark} {t['title']} ({t['points']})", callback_data=f"task:{lab_id}:{t['order']}"
        )])
    text = "\n".join(lines)[:3900]
    if new:
        await tg.send_text(update.effective_message, text, parse_mode=ParseMode.MARKDOWN,
                                                  reply_markup=InlineKeyboardMarkup(rows))
    else:
        await tg.edit_text(update.callback_query, text, parse_mode=ParseMode.MARKDOWN,
                                                      reply_markup=InlineKeyboardMarkup(rows))


async def target_open(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    await _render(update, context, int(q.data.split(":")[1]), new=False)


async def target_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    lab_id = int(q.data.split(":")[1])
    await q.answer("جار تشغيل البيئة…")
    async with SessionLocal() as s:
        lab = await s.get(Lab, lab_id)
        user = await get_user_by_telegram(s, update.effective_user.id)
        res = await svc.start(s, user, lab)
    if not res.get("ok"):
        await q.answer(res.get("error", "تعذّر التشغيل"), show_alert=True)
    await _render(update, context, lab_id, new=False)


async def target_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    lab_id = int(q.data.split(":")[1])
    await q.answer("جار الإيقاف…")
    async with SessionLocal() as s:
        lab = await s.get(Lab, lab_id)
        user = await get_user_by_telegram(s, update.effective_user.id)
        await svc.stop(s, user, lab)
    await _render(update, context, lab_id, new=False)


async def task_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query
    await q.answer()
    _, lab_id, order = q.data.split(":")
    context.user_data["task_lab"] = int(lab_id)
    context.user_data["task_order"] = int(order)
    async with SessionLocal() as s:
        lab = await s.get(Lab, int(lab_id))
    task = next((t for t in (lab.tasks or []) if int(t.get("order", 0)) == int(order)), None)
    prompt = task.get("prompt", "") if task else ""
    await q.message.reply_text(
        f"📝 *{task.get('title', 'مهمة') if task else 'مهمة'}*\n{prompt}\n\n"
        "أرسل إجابتك (اكتب /cancel للإلغاء):",
        parse_mode=ParseMode.MARKDOWN,
    )
    return AWAIT_ANSWER


async def task_submit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lab_id = context.user_data.pop("task_lab", None)
    order = context.user_data.pop("task_order", None)
    value = (update.message.text or "").strip()
    if not lab_id or not order:
        await tg.send_text(update.message, "جلسة منتهية. أعد فتح البيئة.")
        return ConversationHandler.END
    async with SessionLocal() as s:
        lab = await s.get(Lab, lab_id)
        user = await get_user_by_telegram(s, update.effective_user.id)
        res = await svc.submit_task(s, user, lab, order, value)
    if not res.get("ok"):
        await tg.send_text(update.message, f"⚠️ {res.get('error')}")
    elif res.get("correct"):
        extra = " (سُجّلت سابقا)" if res.get("already") else f" +{res['xp']} نقطة"
        await tg.send_text(update.message, f"✅ إجابة صحيحة!{extra}")
    else:
        await tg.send_text(update.message, "❌ إجابة غير صحيحة. حاول مرة أخرى.")
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("task_lab", None)
    context.user_data.pop("task_order", None)
    await tg.send_text(update.message, "تم الإلغاء.")
    return ConversationHandler.END


def targets_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(task_entry, pattern=r"^task:\d+:\d+$")],
        states={AWAIT_ANSWER: [MessageHandler(filters.TEXT & ~filters.COMMAND, task_submit)]},
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
        per_message=True,
    )


def register_handlers(app) -> None:
    app.add_handler(CallbackQueryHandler(target_open, pattern=r"^target:\d+$"))
    app.add_handler(CallbackQueryHandler(target_start, pattern=r"^tstart:\d+$"))
    app.add_handler(CallbackQueryHandler(target_stop, pattern=r"^tstop:\d+$"))
