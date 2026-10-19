# -*- coding: utf-8 -*-
"""نقطة إقلاع بوت تلجرام.

يعمل بمجرد ضبط BOT_TOKEN في .env — وضعان: polling (محلي) أو webhook (نشر).
يشغّل معه عامل توليد المحتوى في الخلفية (Outline-first + Lazy fill).
"""
from __future__ import annotations

import asyncio

from telegram import BotCommand, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    ApplicationHandlerStop,
    TypeHandler,
)

from app.handlers import (
    admin,
    assistant,
    auth,
    export,
    labs,
    languages,
    learn,
    menu,
    paths,
    profile,
    qa,
    runner,
    search,
    start,
    targets,
    tools,
)
from app.scheduler import setup_jobs
from core.config import settings
from core.db import close_db, init_db
from core.logging import get_logger, setup_logging

setup_logging()
log = get_logger("bot")

COMMANDS = [
    BotCommand("start", "بدء / القائمة الرئيسية"),
    BotCommand("menu", "إظهار الأزرار"),
    BotCommand("register", "إنشاء حساب"),
    BotCommand("login", "تسجيل الدخول"),
    BotCommand("courses", "الكورسات والدروس"),
    BotCommand("languages", "اللغات العالمية (48)"),
    BotCommand("paths", "المسارات التعلّمية"),
    BotCommand("search", "بحث في كل المحتوى"),
    BotCommand("ask", "المساعد الذكي"),
    BotCommand("run", "تشغيل كود"),
    BotCommand("tools", "أدوات اختبار الويب"),
    BotCommand("daily", "الدرس اليومي"),
    BotCommand("rank", "لوحة الصدارة"),
    BotCommand("me", "حسابي وتقدّمي"),
    BotCommand("notes", "ملاحظاتي"),
    BotCommand("bookmarks", "مرجعياتي"),
    BotCommand("certificates", "شهاداتي"),
    BotCommand("export", "تصدير درس"),
    BotCommand("status", "حالة النظام"),
    BotCommand("help", "المساعدة"),
]


async def on_error(update: object, context) -> None:
    log.exception("خطأ أثناء معالجة تحديث: %s", context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "⚠️ حدث خطأ غير متوقع. تم تسجيله وسيتم إصلاحه."
            )
        except Exception:
            pass


async def post_init(app: Application) -> None:
    await app.bot.set_my_commands(COMMANDS)
    me = await app.bot.get_me()
    log.info("البوت يعمل: @%s (id=%s)", me.username, me.id)
    if settings.AI_FREE_MODE:
        log.info("وضع AI: مجاني (%s) — ميزانية %s توكن/يوم",
                 ", ".join(settings.free_providers) or "لا يوجد مزوّد",
                 settings.AI_DAILY_TOKEN_BUDGET or "بلا سقف")
    else:
        log.info("وضع AI: %s", settings.ai_mode)
    setup_jobs(app)
    from pipeline import jobs

    jobs.start_worker()


async def private_only(update: object, context) -> None:
    """يمنع استخدام البوت في المجموعات (خصوصية + منع إغراق التوليد)."""
    if not isinstance(update, Update):
        return
    chat = update.effective_chat
    if chat is None or chat.type == "private":
        return
    if update.effective_message:
        try:
            await update.effective_message.reply_text(
                "🔒 هذا البوت يعمل في المحادثات الخاصة فقط.\n"
                "افتحه مباشرة: @TrsttryBot"
            )
        except Exception:
            pass
    raise ApplicationHandlerStop


async def post_shutdown(app: Application) -> None:
    from pipeline import jobs

    await jobs.stop_worker()


def build_application() -> Application:
    app = (
        ApplicationBuilder()
        .token(settings.BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # حارس المحادثات الخاصة (المجموعة -1 = قبل كل شيء)
    app.add_handler(TypeHandler(Update, private_only), group=-1)

    # المحادثات في مجموعات منفصلة لتجنّب التداخل
    app.add_handler(auth.auth_conversation(), group=1)
    app.add_handler(labs.labs_conversation(), group=2)
    app.add_handler(profile.notes_conversation(), group=3)
    app.add_handler(targets.targets_conversation(), group=4)
    app.add_handler(assistant.ask_conversation(), group=5)
    app.add_handler(search.search_conversation(), group=6)
    app.add_handler(runner.run_conversation(), group=7)
    app.add_handler(tools.tools_conversation(), group=8)
    app.add_handler(qa.qa_conversation(), group=9)

    # الأوامر والـcallbacks (المجموعة 0)
    menu.register_handlers(app)
    start.register_handlers(app)
    learn.register_handlers(app)
    paths.register_handlers(app)
    languages.register_handlers(app)
    labs.register_handlers(app)
    profile.register_handlers(app)
    targets.register_handlers(app)
    assistant.register_handlers(app)
    export.register_handlers(app)
    qa.register_handlers(app)
    search.register_handlers(app)
    runner.register_handlers(app)
    tools.register_handlers(app)
    admin.register_handlers(app)

    app.add_error_handler(on_error)
    return app


def _run() -> None:
    errors = settings.check_required()
    if errors:
        for e in errors:
            log.error("لا يمكن الإقلاع — %s", e)
        log.error("اضبط المتطلبات في ملف .env ثم أعد التشغيل.")
        raise SystemExit(1)
    for w in settings.check_warnings():
        log.warning("تحذير — %s", w)

    asyncio.run(init_db())
    app = build_application()

    try:
        if settings.BOT_MODE == "webhook" and settings.WEBHOOK_URL:
            log.info("تشغيل البوت بوضع Webhook: %s", settings.WEBHOOK_URL)
            app.run_webhook(
                listen="0.0.0.0",
                port=settings.WEBHOOK_PORT,
                url_path=settings.WEBHOOK_PATH,
                webhook_url=settings.WEBHOOK_URL,
                secret_token=settings.WEBHOOK_SECRET or None,
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True,
            )
        else:
            log.info("تشغيل البوت بوضع Polling...")
            app.run_polling(
                allowed_updates=Update.ALL_TYPES, drop_pending_updates=True
            )
    finally:
        asyncio.run(close_db())


if __name__ == "__main__":
    try:
        _run()
    except (KeyboardInterrupt, SystemExit):
        pass
