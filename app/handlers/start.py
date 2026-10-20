# -*- coding: utf-8 -*-
"""معالجات البداية والقوائم وحساب المستخدم."""
from __future__ import annotations

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from app.keyboards import main_reply_kb, welcome_kb
from app.handlers.common import spawn
from core.config import settings
from core.db import SessionLocal
from core.logging import get_logger
from core.repo import get_user_by_telegram
from app import tg

log = get_logger("bot.start")


async def _prebuild_all(user_id: int) -> None:
    """يبني بالخلفية كل دروس اللغات التي يتعلّمها المستخدم (مرة واحدة عند الدخول)."""
    from pipeline import jobs

    try:
        async with SessionLocal() as s:
            added = await jobs.prebuild_user_languages(s, user_id)
        if added:
            log.info("بناء تلقائي عند الدخول: أُدرجت %s مهمة للمستخدم #%s", added, user_id)
    except Exception as e:  # noqa: BLE001
        log.warning("تعذّر البناء التلقائي عند الدخول: %s", e)

WELCOME = (
    "🎓 *أكاديمية الأمن السيبراني والبرمجة*\n\n"
    "منصّة تعليمية متكاملة تبني مهاراتك من الصفر إلى الاحتراف، "
    "بأسلوب عملي قائم على الفهم العميق والتطبيق لا على الحفظ.\n\n"
    "*ماذا تجد هنا؟*\n"
    "• 📚 *مسارات منظّمة:* 10 مراحل لكل لغة برمجة، تتدرّج من الأساسيات حتى بناء المشاريع.\n"
    "• 🔬 *شروح موسّعة:* كل درس يوضّح الفكرة، وسبب الحاجة إليها، والأخطاء الشائعة، مع أكواد حقيقية.\n"
    "• 🧪 *مختبرات عملية:* تمارين أمنية داخل بيئة معزولة وآمنة تماما.\n"
    "• ✅ *اختبارات ذكية:* تثبّت الفهم وتفتح المرحلة التالية بعد الاجتياز.\n"
    "• 📈 *متابعة مستمرة:* نقاط ومستويات وسلاسل يومية ومراجعة ذكية للدروس السابقة.\n\n"
    "*كيف تبدأ؟*\n"
    "1️⃣ أنشئ حسابك أو سجّل الدخول من الزرين بالأسفل.\n"
    "2️⃣ اختر لغة أو مسارا تعلّميا من القائمة.\n"
    "3️⃣ ادرس الدرس ثم اجتز اختباره لفتح ما بعده.\n"
    "4️⃣ واصل يوميا، ودع المراجعة الذكية تُعيد لك ما يحتاج تثبيتا.\n\n"
    "💡 *نصيحة:* لا تنتقل إلى درس جديد قبل أن تُنجز تمرين الدرس الحالي بنفسك.\n\n"
    "*أوامر سريعة:* /help القائمة الكاملة · /courses الكورسات · /daily درس اليوم"
)


def _returning_text(user) -> str:
    """رسالة العودة: نفس هوية الترحيب، لكن بخطوات متابعة لا بتسجيل جديد."""
    name = tg.escape_md(user.username or user.email or "صديقنا")
    return (
        f"👋 أهلا بعودتك، *{name}*!\n\n"
        "🎓 *أكاديمية الأمن السيبراني والبرمجة*\n\n"
        f"📊 تقدّمك حتى الآن: المستوى {user.level} · {user.xp} نقطة · "
        f"سلسلة {user.streak_count} يوم.\n\n"
        "*واصل رحلتك من حيث توقفت:*\n"
        "• 📚 *الكورسات* — تصفّح المراحل والدروس وحالة كل درس.\n"
        "• 🌍 *اللغات* — 48 لغة برمجة، لكل منها مسار كامل.\n"
        "• 🎯 *الدرس اليومي* — جرعة قصيرة تحافظ على الاستمرارية.\n"
        "• 🏆 *ترتيبي* — قارن تقدّمك مع بقية المتعلّمين.\n\n"
        "*تذكير سريع:* يُفتح الدرس بعد اجتياز اختبار الدرس الذي قبله، "
        "والمراجعة الذكية تُبرز ما حان موعد تثبيته.\n\n"
        "استخدم الأزرار بالأسفل، أو /help لكل الأوامر."
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tg_id = update.effective_user.id
    async with SessionLocal() as session:
        user = await get_user_by_telegram(session, tg_id)
    if user:
        await tg.send_text(
            update.effective_message,
            _returning_text(user),
            parse_mode="Markdown",
            reply_markup=main_reply_kb(),
        )
        if settings.GEN_PREBUILD_ON_OPEN and settings.ai_configured:
            spawn(_prebuild_all(user.id))
    else:
        await tg.send_text(
            update.effective_message,
            WELCOME,
            parse_mode="Markdown",
            reply_markup=welcome_kb(),
        )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await tg.send_text(update.message, 
        "🤖 *أكاديمية الأمن السيبراني والبرمجة*\n\n"
        "*التعلّم:*\n"
        "/courses الكورسات والدروس\n"
        "/languages اللغات العالمية (48 لغة)\n"
        "/paths المسارات التعلّمية\n"
        "/daily الدرس اليومي\n"
        "/search بحث في كل المحتوى\n\n"
        "*أدوات:*\n"
        "/ask اسأل المساعد الذكي\n"
        "/run تشغيل كود داخل بيئة معزولة\n"
        "/tools أدوات اختبار الويب\n\n"
        "*حسابك:*\n"
        "/me حسابي · /rank الصدارة\n"
        "/notes ملاحظاتي · /bookmarks مرجعياتي\n"
        "/certificates شهاداتي\n"
        "/status حالة النظام · /menu إظهار الأزرار\n"
        "/cancel إلغاء أي إدخال",
        parse_mode="Markdown",
    )


async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await tg.send_text(update.message, "القائمة جاهزة 👇", reply_markup=main_reply_kb())


async def my_account(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tg_id = update.effective_user.id
    async with SessionLocal() as session:
        user = await get_user_by_telegram(session, tg_id)
        if not user:
            await tg.send_text(update.message, 
                "لم تسجّل بعد. أرسل /start.", reply_markup=welcome_kb()
            )
            return
        # الدروس التي بدأها ولم يكملها
        from sqlalchemy import func, select

        from core.learning import STATUS_IN_PROGRESS
        from core.models import Progress

        started = (await session.execute(
            select(func.count()).select_from(Progress).where(
                Progress.user_id == user.id,
                Progress.status == STATUS_IN_PROGRESS,
            )
        )).scalar() or 0
        passed = (await session.execute(
            select(func.count()).select_from(Progress).where(
                Progress.user_id == user.id,
                Progress.status == "passed",
            )
        )).scalar() or 0

    lines = [
        "👤 *حسابك*\n",
        f"الاسم: {user.username or '—'}",
        f"البريد: {user.email or '—'}",
        f"النقاط: {user.xp}",
        f"المستوى: {user.level}",
        f"السلسلة: {user.streak_count} يوم",
        f"دروس مكتملة: {passed}",
    ]
    if started:
        lines.append(f"دروس قيد التعلّم: {started}")
    await tg.send_text(update.message, "\n".join(lines), parse_mode="Markdown")


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from pipeline.sandbox_runner import docker_available
    from pipeline.providers import usage_snapshot

    docker_on = await docker_available()
    if docker_on:
        exec_mode = "Docker + محلي" if settings.SANDBOX_LOCAL else "Docker فقط"
    elif settings.SANDBOX_LOCAL:
        exec_mode = "محلي (بيئة نظيفة + حدود موارد)"
    else:
        exec_mode = "معطّل (فعّل SANDBOX_LOCAL=1 أو شغّل Docker)"

    db = "SQLite" if settings.is_sqlite else "PostgreSQL"
    targets = "هدف خارجي/حاويات" if docker_on else ("هدف خارجي" if settings.external_target_urls else "نمط موجّه")
    
    # معلومات AI
    ai_mode = settings.ai_mode
    providers = ", ".join(settings.free_providers) if settings.free_providers else "لا يوجد"
    usage = await usage_snapshot()
    if usage:
        usage_lines = "\n".join(f"  {u['provider']}: {u['requests']} طلب / {u['tokens']} توكن" for u in usage)
        usage_str = f"\n📊 استهلاك اليوم:\n{usage_lines}"
    else:
        usage_str = ""
    
    text = (
        "⚙️ *حالة النظام*\n"
        f"🗄️ قاعدة البيانات: {db}\n"
        f"🐳 Docker: {'متاح' if docker_on else 'غير متاح'}\n"
        f"▶️ تنفيذ الأكواد: {exec_mode}\n"
        f"🎯 بيئات الهدف: {targets}\n"
        f"🛰️ البوت: {settings.BOT_MODE}\n"
        f"🤖 وضع AI: {ai_mode} ({providers}){usage_str}"
    )
    await tg.send_text(update.message, text, parse_mode="Markdown")


def register_handlers(app) -> None:
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("me", my_account))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("menu", menu_cmd))
