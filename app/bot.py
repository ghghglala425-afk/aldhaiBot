# -*- coding: utf-8 -*-
"""نقطة إقلاع بوت تلجرام.

يعمل بمجرد ضبط BOT_TOKEN في .env — وضعان: polling (محلي) أو webhook (نشر).
يشغّل معه عامل توليد المحتوى في الخلفية (Outline-first + Lazy fill).
"""
from __future__ import annotations

import asyncio
import os

from telegram import BotCommand, Update
from telegram.error import Conflict, NetworkError, TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    ApplicationHandlerStop,
    TypeHandler,
    Updater,
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
    study,
    targets,
    tools,
)
from app.scheduler import setup_jobs
from core.config import settings
from core.db import close_db, init_db
from core.logging import get_logger, setup_logging

setup_logging()
log = get_logger("bot")

# =============================================================================
#  كاشف التعارض (نسخة ثانية تعمل بنفس التوكن)
# =============================================================================
_conflict_state = {"count": 0, "notified": False}


def _updater_error(error: Exception) -> None:
    """يُستدعى عند خطأ في جلب التحديثات.

    `Conflict` يعني أن هناك نسخة أخرى تعمل بنفس التوكن — في هذه الحالة
    لا تصل أي رسالة والبوت يبدو "ميتا" بلا سبب واضح. نُبلغ المشرف.
    """
    if isinstance(error, Conflict):
        _conflict_state["count"] += 1
        n = _conflict_state["count"]
        if n == 1:
            log.error(
                "⛔ تعارض: هناك نسخة أخرى من البوت تعمل بنفس التوكن. "
                "أوقفها (أو احذف الخدمة القديمة في Railway)."
            )
        elif n == 5 and not _conflict_state["notified"]:
            _conflict_state["notified"] = True
            log.error("⛔ تعارض مستمر (%s محاولات) — البوت لا يستقبل أي رسالة.", n)
            _notify_admins_conflict()
        return

    if isinstance(error, NetworkError):
        log.warning("⚠️ خطأ شبكة مؤقت: %s", error)
        return

    log.error("خطأ في جلب التحديثات: %s", error)


async def _notify_admins_conflict() -> None:
    """تنبيه المشرفين بتعارض التوكن (فشل صامت)."""
    if not settings.admin_ids:
        return
    try:
        from telegram import Bot

        bot = Bot(settings.BOT_TOKEN)
        for admin_id in settings.admin_ids:
            try:
                await bot.send_message(
                    admin_id,
                    "⛔ <b>تعارض في البوت</b>\n\n"
                    "هناك نسخة أخرى من هذا البوت تعمل بنفس التوكن، لذلك لا يصل "
                    "أي رسالة جديدة.\n\n"
                    "الحل: أوقف النسخة القديمة (خدمة Railway أخرى، أو عملية محلية، "
                    "أو خادم آخر) ثم أعد التشغيل.",
                    parse_mode="HTML",
                )
            except TelegramError:
                continue
    except Exception as e:  # noqa: BLE001
        log.debug("تعذّر إبلاغ المشرف: %s", e)

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
    BotCommand("hub", "مركز التعلّم والمراجعة"),
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
    """معالج الأخطاء العام.

    `Conflict` = هناك نسخة أخرى تعمل بنفس التوكن. في هذه الحالة لا يصل
    أي تحديث، ومعالجتها كخطأ عادي تُظهر «حدث خطأ غير متوقع» بلا فائدة.
    """
    err = getattr(context, "error", None)

    if isinstance(err, Conflict):
        _updater_error(err)
        return

    if isinstance(err, NetworkError):
        log.warning("⚠️ خطأ شبكة مؤقت: %s", err)
        return

    log.exception("خطأ أثناء معالجة تحديث: %s", err)
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

    # زرع البيانات الأساسية إن كانت القاعدة فارغة (قاعدة Railway الجديدة)
    try:
        from pipeline.seed import ensure_seeded

        if await ensure_seeded():
            log.info("تمت زرع البيانات الأساسية.")
    except Exception as e:  # noqa: BLE001
        log.warning("تعذّر زرع البيانات الأساسية: %s", e)

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


class _ConflictAwareUpdater(Updater):
    """محدّث يمرّر كاشف التعارض إلى حلقة Polling.

    PTB لا يتيح تمرير `error_callback` عبر `Application.run_polling`،
    فنتجاوز ذلك هنا. الفائدة: «Conflict» يعني أن نسخة أخرى تعمل بنفس
    التوكن → نُبلغ المشرف بدل الفشل الصامت.
    """

    def start_polling(self, *args, error_callback=None, **kwargs):
        return super().start_polling(
            *args, error_callback=error_callback or _updater_error, **kwargs
        )


def build_application() -> None | Application:
    """يبني التطبيق. في وضع Webhook لا يُنشأ محدّث polling إطلاقا."""
    if settings.BOT_MODE == "webhook" and settings.WEBHOOK_URL:
        app = (
            ApplicationBuilder()
            .token(settings.BOT_TOKEN)
            .post_init(post_init)
            .post_shutdown(post_shutdown)
            .build()
        )
    else:
        # polling — مع كاشف تعارض يُبلغ المشرف
        from telegram import Bot

        bot = Bot(settings.BOT_TOKEN)
        updater = _ConflictAwareUpdater(bot=bot, update_queue=asyncio.Queue())
        app = (
            ApplicationBuilder()
            .updater(updater)
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
    study.register_handlers(app)
    admin.register_handlers(app)

    app.add_error_handler(on_error)
    return app


def _detect_platform() -> None:
    """تعديل إعدادات المضيف (Railway / PaaS) قبل الإقلاع.

    Railway يحقن تلقائيا:
      - PORT                  → المنفذ الذي يجب الاستماع عليه
      - RAILWAY_PUBLIC_DOMAIN → النطاق العام للخدمة (لـ webhook و Mini App)
    """
    port = os.environ.get("PORT", "").strip()
    if port.isdigit():
        settings.WEBHOOK_PORT = int(port)
        log.info("اكتُشف منفذ المضيف PORT=%s", port)

    domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
    if domain:
        settings.WEBHOOK_URL = f"https://{domain}"
        settings.WEBHOOK_PATH = settings.WEBHOOK_PATH or "/webhook"
        settings.MINIAPP_URL = settings.MINIAPP_URL or f"https://{domain}"
        log.info("اكتُشف نطاق Railway: %s", domain)


def _start_health_server(port: int) -> None:
    """خادم صحي صغير في خيط منفصل — يخدم /health على Railway.

    البوت في وضع Polling لا يستمع على أي منفذ، وبلا هذا الخادم تعتبر
    Railway الخدمة غير سليمة (Connection refused) فتعيد تشغيلها في حلقة.
    """
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class _HealthHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _reply(self, code: int, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except OSError:
                pass

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0].rstrip("/") or "/"
            if path in ("/health", "/healthz"):
                self._reply(200, b'{"status":"ok","service":"bot"}')
            else:
                self._reply(404, b'{"error":"not found"}')

        def log_message(self, *args) -> None:  # noqa: D102
            return

    try:
        server = ThreadingHTTPServer(("0.0.0.0", port), _HealthHandler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        log.info("خادم الفحص الصحي يعمل على المنفذ %s", port)
    except OSError as e:
        log.warning("تعذّر تشغيل خادم الفحص الصحي على %s: %s", port, e)


def _run() -> None:
    errors = settings.check_required()
    if errors:
        for e in errors:
            log.error("لا يمكن الإقلاع — %s", e)
        log.error("اضبط المتطلبات في ملف .env ثم أعد التشغيل.")
        raise SystemExit(1)
    for w in settings.check_warnings():
        log.warning("تحذير — %s", w)

    _detect_platform()

    asyncio.run(init_db())
    app = build_application()

    # خادم الفحص الصحي (يلزم في Railway حيث لا يوجد Polling listener)
    if os.environ.get("PORT", "").strip().isdigit():
        _start_health_server(settings.WEBHOOK_PORT)

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
