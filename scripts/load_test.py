# -*- coding: utf-8 -*-
"""اختبار حمل واقعي: 50 مستخدمًا متزامنًا يمرّون برحلة التعلّم الكاملة.

كل مستخدم مؤقت يقوم بـ: تسجيل → /me → المسارات → الدرس اليومي → دروس
الكورس → جلب الاختبار → تسليم محاولة → المجتمع. يقيس السكربت زمن كل نقطة
(p50/p95/p99/الأقصى)، وأكواد HTTP، والأخطاء، ثم يحذف الحسابات المؤقتة.

الاستخدام (من داخل الحاوية حيث DATABASE_URL وAI متاحان):

    python -m scripts.load_test --users 50 --concurrency 10
    python -m scripts.load_test --users 50 --concurrency 25 --with-ai
    python -m scripts.load_test --users 10 --keep --json-out result.json

ملاحظات:
- بدون DATABASE_URL تُنشأ الحسابات ولا تُحذف (تحذير واضح في البداية).
- `--with-ai` يستدعي مزوّدي الذكاء الاصطناعي فعليًا (يستهلك حصة).
- الإجابات الصحيحة تُقرأ من القاعدة إن أمكن، وإلا تُستخدم الخيارات الأولى
  لقياس زمن النقطة فقط (لا يهم النجاح هنا).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
import uuid
from collections import Counter, defaultdict
from pathlib import Path

try:
    ROOT = Path(__file__).resolve().parents[1]
except NameError:  # يُشغَّل عبر exec داخل الحاوية
    ROOT = Path.cwd()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_BASE = os.getenv("API_BASE_URL", "https://aldhaibot-production.up.railway.app")
PASSWORD = "LoadTest123!"
PREFIX = "loadtest"
COURSE_SLUG = "python-security"


# ---------------------------------------------------------------------
#  إحصاءات
# ---------------------------------------------------------------------
class Stats:
    """يجمع زمن/كود كل نقطة نهاية ويحسب المئينات."""

    def __init__(self) -> None:
        self.latency: dict[str, list[float]] = defaultdict(list)
        self.codes: dict[str, Counter] = defaultdict(Counter)
        self.errors: list[dict] = []

    def add(self, endpoint: str, status: int, seconds: float, error: str = "") -> None:
        self.latency[endpoint].append(seconds * 1000.0)
        self.codes[endpoint][status] += 1
        if error:
            self.errors.append({"endpoint": endpoint, "status": status, "error": error})

    @staticmethod
    def percentile(values: list[float], p: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        idx = int(round((p / 100.0) * (len(ordered) - 1)))
        return ordered[max(0, min(len(ordered) - 1, idx))]

    def table(self) -> list[dict]:
        rows = []
        for endpoint, values in self.latency.items():
            codes = self.codes[endpoint]
            bad = sum(n for code, n in codes.items() if code == 0 or code >= 500)
            rows.append(
                {
                    "endpoint": endpoint,
                    "n": len(values),
                    "p50": round(self.percentile(values, 50), 1),
                    "p95": round(self.percentile(values, 95), 1),
                    "p99": round(self.percentile(values, 99), 1),
                    "max": round(max(values), 1),
                    "avg": round(statistics.fmean(values), 1),
                    "bad": bad,
                    "codes": dict(codes),
                }
            )
        rows.sort(key=lambda r: r["endpoint"])
        return rows


# ---------------------------------------------------------------------
#  HTTP
# ---------------------------------------------------------------------
async def _call(
    client,
    stats: Stats,
    endpoint: str,
    method: str,
    path: str,
    *,
    token: str | None = None,
    body: dict | None = None,
    expect: tuple[int, ...] = (200, 201),
) -> tuple[int, object]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    started = time.perf_counter()
    try:
        response = await client.request(
            method, path, json=body, headers=headers, timeout=90
        )
        elapsed = time.perf_counter() - started
        try:
            payload: object = response.json()
        except Exception:  # noqa: BLE001
            payload = response.text[:200]
        status = response.status_code
        error = ""
        if status not in expect:
            error = f"HTTP {status}: {str(payload)[:160]}"
        stats.add(endpoint, status, elapsed, error)
        return status, payload
    except Exception as e:  # noqa: BLE001
        stats.add(endpoint, 0, time.perf_counter() - started, f"{type(e).__name__}: {e}")
        return 0, str(e)[:200]


def _attempt_responses(quiz: object) -> dict[str, list[int]]:
    """يبني ردود محاولة من خيارات الاختبار (للقياس فقط)."""
    questions = quiz.get("questions") if isinstance(quiz, dict) else None
    if not isinstance(questions, list):
        return {}
    out: dict[str, list[int]] = {}
    for question in questions:
        options = question.get("options") or []
        if options:
            out[str(question.get("id"))] = [options[0].get("id")]
    return out


# ---------------------------------------------------------------------
#  رحلة المستخدم
# ---------------------------------------------------------------------
async def _register(client, stats: Stats, email: str, username: str) -> str | None:
    status, payload = await _call(
        client,
        stats,
        "auth/register",
        "POST",
        "/api/auth/register",
        body={"email": email, "password": PASSWORD, "username": username},
        expect=(201, 200, 400),
    )
    if isinstance(payload, dict) and payload.get("token"):
        return str(payload["token"])
    # موجود مسبقًا (تشغيل سابق): جرّب الدخول.
    status, payload = await _call(
        client,
        stats,
        "auth/login",
        "POST",
        "/api/auth/login",
        body={"email": email, "password": PASSWORD},
    )
    if isinstance(payload, dict) and payload.get("token"):
        return str(payload["token"])
    return None


async def _user_journey(
    client,
    stats: Stats,
    index: int,
    run_id: str,
    answers_cache: dict[int, dict[str, list[int]]],
) -> None:
    email = f"{PREFIX}-{run_id}-{index}@loadtest.local"
    username = f"lt{run_id}{index}"
    token = await _register(client, stats, email, username)
    if not token:
        return

    await _call(client, stats, "auth/me", "GET", "/api/auth/me", token=token)
    await _call(client, stats, "paths", "GET", "/api/paths", token=token)
    await _call(client, stats, "daily", "GET", "/api/daily", token=token)

    status, lessons = await _call(
        client,
        stats,
        "course/lessons",
        "GET",
        f"/api/courses/{COURSE_SLUG}/lessons",
        token=token,
    )
    lesson_id = None
    if isinstance(lessons, list) and lessons:
        lesson_id = lessons[0].get("id")
    if not lesson_id:
        return

    status, quiz = await _call(
        client,
        stats,
        "lesson/quiz",
        "GET",
        f"/api/lessons/{lesson_id}/quiz",
        token=token,
    )
    responses = answers_cache.get(int(lesson_id)) or _attempt_responses(quiz)
    if responses:
        await _call(
            client,
            stats,
            "lesson/attempt",
            "POST",
            f"/api/lessons/{lesson_id}/attempt",
            token=token,
            body={"responses": responses},
        )
    await _call(client, stats, "leaderboard", "GET", "/api/leaderboard", token=token)
    await _call(client, stats, "notes", "GET", "/api/notes", token=token)


# ---------------------------------------------------------------------
#  الإجابات الصحيحة (اختياري عبر القاعدة)
# ---------------------------------------------------------------------
async def _load_correct_answers(lesson_ids: list[int] | None = None) -> dict[int, dict[str, list[int]]]:
    """يقرأ الإجابات الصحيحة من القاعدة إن كان DATABASE_URL متاحًا."""
    if not os.getenv("DATABASE_URL"):
        return {}
    try:
        from sqlalchemy import select

        from core.db import SessionLocal, init_db
        from core.models import Course, Lesson, Option, Question, Quiz, Stage

        await init_db()
        out: dict[int, dict[str, list[int]]] = {}
        async with SessionLocal() as s:
            ids = list(lesson_ids or [])
            if not ids:
                ids = list(
                    (
                        await s.execute(
                            select(Lesson.id)
                            .join(Stage, Lesson.stage_id == Stage.id)
                            .join(Course, Stage.course_id == Course.id)
                            .where(Course.slug == COURSE_SLUG)
                            .order_by(Stage.order_index, Lesson.order_index)
                            .limit(20)
                        )
                    ).scalars()
                )
            for lesson_id in ids:
                quiz = await s.scalar(select(Quiz).where(Quiz.lesson_id == lesson_id))
                if not quiz:
                    continue
                questions = list(
                    (
                        await s.execute(
                            select(Question).where(Question.quiz_id == quiz.id)
                        )
                    ).scalars()
                )
                payload: dict[str, list[int]] = {}
                for question in questions:
                    options = list(
                        (
                            await s.execute(
                                select(Option).where(
                                    Option.question_id == question.id,
                                    Option.is_correct.is_(True),
                                )
                            )
                        ).scalars()
                    )
                    payload[str(question.id)] = [o.id for o in options]
                if payload:
                    out[int(lesson_id)] = payload
        return out
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] تعذّر قراءة الإجابات الصحيحة: {type(e).__name__}: {e}")
        return {}


async def _cleanup(prefix_ids: str) -> int:
    """يحذف الحسابات المؤقتة وكل سجلاتها (CASCADE)."""
    if not os.getenv("DATABASE_URL"):
        return 0
    try:
        from sqlalchemy import delete

        from core.db import SessionLocal
        from core.models import User

        async with SessionLocal() as s:
            result = await s.execute(
                delete(User).where(User.email.like(f"{PREFIX}-{prefix_ids}-%"))
            )
            await s.commit()
            return int(result.rowcount or 0)
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] تعذّر حذف الحسابات المؤقتة: {type(e).__name__}: {e}")
        return 0


# ---------------------------------------------------------------------
#  الذكاء الاصطناعي (اختياري)
# ---------------------------------------------------------------------
async def _ai_probe(prompts: int, concurrency: int) -> dict:
    try:
        from core.config import settings
        from pipeline.ai import chat_text

        if not settings.ai_configured:
            return {"skipped": "لا يوجد مزوّد AI مضبوط في هذه العملية."}
    except Exception as e:  # noqa: BLE001
        return {"skipped": f"تعذّر تحميل طبقة AI: {e}"}

    semaphore = asyncio.Semaphore(max(1, concurrency))
    results: list[tuple[bool, float, str]] = []

    async def _one(i: int) -> None:
        async with semaphore:
            started = time.perf_counter()
            try:
                text = await chat_text(
                    "أجب بسطر واحد موجز بالعربية.",
                    "ما هو الفرق بين HTTP وHTTPS؟",
                    max_tokens=120,
                    timeout=60,
                )
                ok = bool((text or "").strip())
                results.append((ok, time.perf_counter() - started, "" if ok else "رد فارغ"))
            except Exception as e:  # noqa: BLE001
                results.append((False, time.perf_counter() - started, str(e)[:120]))

    await asyncio.gather(*[_one(i) for i in range(max(1, prompts))])
    latencies = [r[1] * 1000 for r in results]
    return {
        "prompts": len(results),
        "ok": sum(1 for r in results if r[0]),
        "p50_ms": round(Stats.percentile(latencies, 50), 1),
        "p95_ms": round(Stats.percentile(latencies, 95), 1),
        "max_ms": round(max(latencies) if latencies else 0, 1),
        "errors": [r[2] for r in results if r[2]][:5],
    }


# ---------------------------------------------------------------------
#  التشغيل
# ---------------------------------------------------------------------
def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="اختبار حمل لرحلة التعلّم عبر API")
    parser.add_argument("--base", default=DEFAULT_BASE, help="نطاق الخدمة")
    parser.add_argument("--users", type=int, default=50, help="عدد المستخدمين")
    parser.add_argument("--concurrency", type=int, default=10, help="التزامن")
    parser.add_argument("--with-ai", action="store_true", help="قياس زمن الذكاء الاصطناعي")
    parser.add_argument("--ai-prompts", type=int, default=3, help="عدد استدعاءات AI")
    parser.add_argument("--keep", action="store_true", help="لا تحذف الحسابات المؤقتة")
    parser.add_argument("--json-out", default="", help="حفظ النتيجة في ملف JSON")
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> int:
    import httpx

    users = max(1, args.users)
    concurrency = max(1, min(args.concurrency, users))
    run_id = uuid.uuid4().hex[:8]
    print("=" * 74)
    print("اختبار حمل — بوت التعلّم")
    print(f"الخدمة: {args.base}")
    print(f"المستخدمون: {users} · التزامن: {concurrency} · المعرّف: {run_id}")
    if not os.getenv("DATABASE_URL"):
        print("[WARN] DATABASE_URL غير مضبوط: لن تُحذف الحسابات المؤقتة ولن تُقرأ الإجابات.")
    print("=" * 74)

    stats = Stats()
    answers = await _load_correct_answers([])
    limits = httpx.Limits(
        max_connections=concurrency * 2, max_keepalive_connections=concurrency * 2
    )
    started = time.perf_counter()
    async with httpx.AsyncClient(base_url=args.base, limits=limits) as client:
        semaphore = asyncio.Semaphore(concurrency)

        async def _guarded(i: int) -> None:
            async with semaphore:
                try:
                    await _user_journey(client, stats, i, run_id, answers)
                except Exception as e:  # noqa: BLE001
                    stats.add("journey", 0, 0.0, f"{type(e).__name__}: {e}")

        await asyncio.gather(*[_guarded(i) for i in range(users)])
    elapsed = time.perf_counter() - started

    ai_result = None
    if args.with_ai:
        ai_result = await _ai_probe(args.ai_prompts, min(concurrency, args.ai_prompts))

    removed = 0
    if not args.keep:
        removed = await _cleanup(run_id)

    rows = stats.table()
    total_requests = sum(r["n"] for r in rows)
    total_bad = sum(r["bad"] for r in rows)

    print()
    print(f"{'نقطة النهاية':<20}{'n':>5}{'p50':>9}{'p95':>9}{'p99':>9}{'max':>9}{'أخطاء':>8}")
    print("-" * 74)
    for row in rows:
        print(
            f"{row['endpoint']:<20}{row['n']:>5}{row['p50']:>9.1f}"
            f"{row['p95']:>9.1f}{row['p99']:>9.1f}{row['max']:>9.1f}{row['bad']:>8}"
        )
    print("-" * 74)
    print(
        f"إجمالي الطلبات: {total_requests} · أخطاء 5xx/شبكة: {total_bad} · "
        f"الزمن: {elapsed:.1f}s · RPS: {total_requests / elapsed:.1f}"
    )
    for row in rows:
        print(f"  {row['endpoint']}: {row['codes']}")

    if ai_result:
        print()
        if ai_result.get("skipped"):
            print(f"[AI] تم التخطي: {ai_result['skipped']}")
        else:
            print(
                f"[AI] {ai_result['ok']}/{ai_result['prompts']} ناجح · "
                f"p50 {ai_result['p50_ms']}ms · p95 {ai_result['p95_ms']}ms · "
                f"max {ai_result['max_ms']}ms"
            )
            for error in ai_result.get("errors", []):
                print(f"  [AI ERROR] {error}")

    if not args.keep:
        print(f"[تنظيف] حُذف {removed} حسابا مؤقتا." if removed else "[تنظيف] لا حسابات محذوفة.")

    if stats.errors:
        print()
        print("أول الأخطاء:")
        for error in stats.errors[:10]:
            print(f"  [{error['endpoint']}] {error['status']}: {error['error'][:150]}")

    if args.json_out:
        payload = {
            "base": args.base,
            "users": users,
            "concurrency": concurrency,
            "run_id": run_id,
            "elapsed_seconds": round(elapsed, 2),
            "total_requests": total_requests,
            "bad_requests": total_bad,
            "endpoints": rows,
            "errors": stats.errors[:50],
            "ai": ai_result,
            "cleaned_users": removed,
        }
        Path(args.json_out).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[JSON] {args.json_out}")

    # فشل الاختبار فقط عند أخطاء خادم/شبكة حقيقية.
    return 1 if total_bad else 0


def main() -> None:
    raise SystemExit(asyncio.run(_run(_parse_args())))


if __name__ == "__main__":
    main()
