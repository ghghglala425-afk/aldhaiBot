# -*- coding: utf-8 -*-
"""تقرير أسبوعي للمشرف: التعلّم، استهلاك الذكاء الاصطناعي، وتشغيل الكود.

الأرقام تُقرأ من قاعدة البيانات مباشرة (لا استدعاءات AI)، لذا التقرير رخيص
ويمكن تشغيله في أي وقت. يُستخدم من `/report` ومن المهمة الأسبوعية.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select

from core.db import SessionLocal
from core.models import AIUsage, Attempt, CodeExecution, Lesson, Progress, User

# أسماء مختصرة للمزوّدين حتى تبقى الرسالة ضمن حد تلجرام (4096 حرف).
_PROVIDER_LABELS = {
    "gemini": "Gemini",
    "groq": "Groq",
    "openrouter": "OpenRouter",
}


def _label(usage_id: str, specs: dict | None = None) -> str:
    """يحوّل معرّف المسار (provider:key~model) إلى اسم مقروء."""
    spec = (specs or {}).get(usage_id)
    if spec is not None:
        name = _PROVIDER_LABELS.get(spec.name, spec.name)
        return f"{name} · {spec.model}"
    provider, _, rest = (usage_id or "").partition(":")
    model = rest.partition("~")[2] if "~" in rest else rest
    model = model or provider
    if len(model) > 28:
        model = model[:28] + "…"
    return f"{_PROVIDER_LABELS.get(provider, provider)} · {model}"


def _fmt(n: int | None) -> str:
    return f"{int(n or 0):,}"


def _pct(part: int, whole: int) -> str:
    if not whole:
        return "—"
    return f"{100 * part / whole:.0f}%"


async def build_weekly_report(days: int = 7) -> dict:
    """يجمع أرقام آخر `days` يوما (يشمل اليوم الحالي)."""
    now = dt.datetime.now(dt.timezone.utc)
    since = now - dt.timedelta(days=max(1, days))
    since_date = since.date()

    async with SessionLocal() as s:
        users_total = int(await s.scalar(select(func.count()).select_from(User)) or 0)
        users_new = int(
            await s.scalar(
                select(func.count()).select_from(User).where(User.created_at >= since)
            )
            or 0
        )
        users_active = int(
            await s.scalar(
                select(func.count()).select_from(User).where(User.last_seen >= since)
            )
            or 0
        )

        published = int(
            await s.scalar(
                select(func.count())
                .select_from(Lesson)
                .where(Lesson.status == "published")
            )
            or 0
        )
        outline = int(
            await s.scalar(
                select(func.count())
                .select_from(Lesson)
                .where(Lesson.status == "outline")
            )
            or 0
        )

        completed = int(
            await s.scalar(
                select(func.count())
                .select_from(Progress)
                .where(Progress.completed_at >= since)
            )
            or 0
        )
        attempts = int(
            await s.scalar(
                select(func.count())
                .select_from(Attempt)
                .where(Attempt.started_at >= since)
            )
            or 0
        )
        passed = int(
            await s.scalar(
                select(func.count())
                .select_from(Attempt)
                .where(Attempt.started_at >= since, Attempt.passed.is_(True))
            )
            or 0
        )

        code_runs = int(
            await s.scalar(
                select(func.count())
                .select_from(CodeExecution)
                .where(CodeExecution.created_at >= since)
            )
            or 0
        )
        code_ok = int(
            await s.scalar(
                select(func.count())
                .select_from(CodeExecution)
                .where(
                    CodeExecution.created_at >= since,
                    CodeExecution.status == "ok",
                )
            )
            or 0
        )
        code_avg = await s.scalar(
            select(func.avg(CodeExecution.execution_time_ms)).where(
                CodeExecution.created_at >= since
            )
        )
        top_langs = [
            (lang or "?", int(cnt or 0))
            for lang, cnt in (
                await s.execute(
                    select(CodeExecution.language, func.count())
                    .where(CodeExecution.created_at >= since)
                    .group_by(CodeExecution.language)
                    .order_by(func.count().desc())
                    .limit(3)
                )
            ).all()
        ]

        try:
            from pipeline.providers import build_providers

            specs = {p.usage_id: p for p in build_providers()}
        except Exception:  # noqa: BLE001
            specs = {}

        ai_rows = (
            await s.execute(
                select(
                    AIUsage.provider,
                    func.sum(AIUsage.requests),
                    func.sum(AIUsage.tokens),
                    func.sum(AIUsage.errors),
                )
                .where(AIUsage.day >= since_date)
                .group_by(AIUsage.provider)
                .order_by(func.sum(AIUsage.tokens).desc())
            )
        ).all()
        ai_paths = [
            {
                "id": str(provider),
                "label": _label(str(provider), specs),
                "requests": int(requests or 0),
                "tokens": int(tokens or 0),
                "errors": int(errors or 0),
            }
            for provider, requests, tokens, errors in ai_rows
        ]

        from pipeline.jobs import queue_stats

        queue = await queue_stats(s)

    return {
        "from": since,
        "to": now,
        "days": max(1, days),
        "users": {
            "total": users_total,
            "new": users_new,
            "active": users_active,
        },
        "learning": {
            "completed": completed,
            "attempts": attempts,
            "passed": passed,
            "published": published,
            "outline": outline,
        },
        "code": {
            "runs": code_runs,
            "ok": code_ok,
            "avg_ms": float(code_avg or 0),
            "top_languages": top_langs,
        },
        "ai": {
            "paths": ai_paths,
            "requests": sum(p["requests"] for p in ai_paths),
            "tokens": sum(p["tokens"] for p in ai_paths),
            "errors": sum(p["errors"] for p in ai_paths),
        },
        "queue": queue,
    }


def render_report(data: dict) -> str:
    """يحوّل الأرقام إلى رسالة HTML جاهزة لـ Telegram."""
    start = data["from"].strftime("%Y-%m-%d")
    end = data["to"].strftime("%Y-%m-%d")
    users = data["users"]
    learn = data["learning"]
    code = data["code"]
    ai = data["ai"]
    queue = data["queue"]

    lines = [
        "📊 <b>التقرير الأسبوعي</b>",
        f"<i>{start} → {end} (UTC)</i>",
        "",
        "👥 <b>المستخدمون</b>",
        f"• الإجمالي: <b>{_fmt(users['total'])}</b> · "
        f"جدد: <b>{_fmt(users['new'])}</b> · "
        f"نشطون: <b>{_fmt(users['active'])}</b>",
        "",
        "🎓 <b>التعلّم</b>",
        f"• دروس مكتملة: <b>{_fmt(learn['completed'])}</b>",
        f"• محاولات اختبار: {_fmt(learn['attempts'])} · "
        f"ناجحة: {_fmt(learn['passed'])} ({_pct(learn['passed'], learn['attempts'])})",
        f"• المحتوى: منشور {_fmt(learn['published'])} · "
        f"مخطط {_fmt(learn['outline'])}",
        "",
        "🤖 <b>الذكاء الاصطناعي</b>",
        f"• الطلبات: <b>{_fmt(ai['requests'])}</b> · "
        f"التوكنز: <b>{_fmt(ai['tokens'])}</b> · "
        f"أخطاء: {_fmt(ai['errors'])}",
    ]
    if ai["paths"]:
        for path in ai["paths"][:4]:
            detail = f"{_fmt(path['requests'])} طلب · {_fmt(path['tokens'])} توكن"
            if path["errors"]:
                detail += f" · أخطاء {path['errors']}"
            lines.append(
                f"  – <code>{path.get('label') or _label(path['id'])}</code>: {detail}"
            )
    else:
        lines.append("  – لا استهلاك مسجّل في هذه الفترة.")

    lines += [
        "",
        "⚙️ <b>تشغيل الكود</b>",
        f"• التشغيلات: <b>{_fmt(code['runs'])}</b> · "
        f"ناجحة: {_fmt(code['ok'])} ({_pct(code['ok'], code['runs'])})",
        f"• متوسط الزمن: {code['avg_ms'] / 1000:.2f} ثانية",
    ]
    if code["top_languages"]:
        langs = " · ".join(f"{lang} ({_fmt(cnt)})" for lang, cnt in code["top_languages"])
        lines.append(f"• أكثر اللغات: {langs}")

    lines += [
        "",
        "📚 <b>طابور التوليد</b>",
        f"• في الانتظار: {_fmt(queue.get('queued', 0))} · "
        f"جارٍ: {_fmt(queue.get('running', 0))} · "
        f"فشل: {_fmt(queue.get('failed', 0))}",
        f"• مكتمل: دروس {_fmt(queue.get('lesson_done', 0))} · "
        f"مخططات {_fmt(queue.get('outline_done', 0))}",
    ]

    text = "\n".join(lines)
    if len(text) > 3900:
        text = text[:3890] + "\n…"
    return text
