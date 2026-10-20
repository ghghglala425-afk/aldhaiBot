# -*- coding: utf-8 -*-
"""معالجات البداية والقوائم وحساب المستخدم."""
from __future__ import annotations

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from app.keyboards import main_reply_kb, menu_with_app, welcome_kb
from core.config import settings
from core.db import SessionLocal
from core.logging import get_logger
from core.repo import get_user_by_telegram

log = get_logger("bot.start")

WELCOME = (
    "🎓 *أكاديمية الأمن السيبراني والبرمجة*\n\n"
    "منصّة تعلّم شاملة: دروس مفصّلة، أكواد حقيقية، مختبرات عملية، "
    "واختبارات لكل مرحلة.\n\n"
    "ابدأ بإنشاء حساب أو الدخول."
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tg_id = update.effective_user.id
    async with SessionLocal() as session:
        user = await get_user_by_telegram(session, tg_id)
    if user:
        await update.message.reply_text(
            f"👋 أهلا بعودتك {user.username or user.email}!\nاستخدم الأزرار بالأسفل.",
            reply_markup=main_reply_kb(),
        )
    else:
        await update.message.reply_text(
            WELCOME, parse_mode="Markdown", reply_markup=welcome_kb()
        )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
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
    await update.message.reply_text("القائمة جاهزة 👇", reply_markup=main_reply_kb())


async def my_account(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tg_id = update.effective_user.id
    async with SessionLocal() as session:
        user = await get_user_by_telegram(session, tg_id)
        if not user:
            await update.message.reply_text(
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
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from pipeline.sandbox_runner import docker_available
    from pipeline.providers import usage_snapshot

    docker_on = await docker_available()
    if settings.SANDBOX_LOCAL and settings.VERIFY_EXEC:
        exec_mode = "محلي (SANDBOX_LOCAL=1 — بلا عزل)"
    elif settings.VERIFY_EXEC:
        exec_mode = "Docker فقط" if docker_on else "معطّل (لا Docker، والتنفيذ المحلي مغلق)"
    else:
        exec_mode = "معطّل (VERIFY_EXEC=0 — تحقق نحوي فقط)"

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
    await update.message.reply_text(text, parse_mode="Markdown")


def register_handlers(app) -> None:
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("me", my_account))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("menu", menu_cmd))
