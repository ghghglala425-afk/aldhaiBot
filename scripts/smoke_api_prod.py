# -*- coding: utf-8 -*-
"""اختبار دخاني شامل لواجهة API عبر نطاق الإنتاج.

ينشئ **حسابا مؤقتا** عبر /api/auth/register، يفحص كل النقاط الأساسية،
يخضع لاختبار درس بإجابات صحيحة (تُقرأ من القاعدة) ويتحقق من النجاح،
ثم **يحذف الحساب المؤقت** وكل سجلاته (CASCADE) في النهاية.

يحتاج:
    DATABASE_URL  (للقراءة/التنظيف فقط)
    API_BASE_URL  (افتراضي: نطاق الإنتاج)

    railway connect Postgres --tunnel-only -P 5433   # نافذة أخرى
    python scripts/smoke_api_prod.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    ROOT = Path(__file__).resolve().parents[1]
except NameError:  # يُشغَّل عبر exec داخل الحاوية
    ROOT = Path.cwd()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FAILS: list[str] = []
OKS: list[str] = []


def fail(msg: str) -> None:
    FAILS.append(msg)
    print(f"[FAIL] {msg}")


def ok(msg: str) -> None:
    OKS.append(msg)
    print(f"[OK]   {msg}")


def request(
    base: str,
    method: str,
    path: str,
    *,
    token: str | None = None,
    body: dict | None = None,
) -> tuple[int, object]:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        base.rstrip("/") + path, data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            raw = r.read()
            try:
                return r.status, json.loads(raw)
            except json.JSONDecodeError:
                return r.status, raw[:300]
    except urllib.error.HTTPError as e:
        raw = e.read()[:400].decode("utf-8", "replace")
        return e.code, raw
    except Exception as e:  # noqa: BLE001
        return 0, str(e)[:250]


async def correct_answers(lesson_id: int) -> dict[int, list[int]]:
    """يقرأ الإجابات الصحيحة من القاعدة مباشرة (قراءة فقط) مع إعادة محاولة."""
    from sqlalchemy import select
    from sqlalchemy.exc import SQLAlchemyError

    from core.db import SessionLocal, engine
    from core.models import Option, Question, Quiz

    for attempt in range(1, 5):
        try:
            async with SessionLocal() as s:
                quiz = await s.scalar(select(Quiz).where(Quiz.lesson_id == lesson_id))
                if not quiz:
                    return {}
                qs = list(
                    (
                        await s.execute(select(Question).where(Question.quiz_id == quiz.id))
                    ).scalars()
                )
                payload: dict[int, list[int]] = {}
                for q in qs:
                    opts = list(
                        (
                            await s.execute(
                                select(Option).where(
                                    Option.question_id == q.id, Option.is_correct.is_(True)
                                )
                            )
                        ).scalars()
                    )
                    payload[q.id] = [o.id for o in opts]
                return payload
        except SQLAlchemyError as e:  # noqa: BLE001
            print(f"[WARN] قراءة الإجابات (محاولة {attempt}) فشلت: {type(e).__name__}")
            try:
                await engine.dispose()
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(3)
    return {}


async def cleanup(user_id: int | None = None, email: str | None = None) -> None:
    """يحذف الحساب المؤقت (CASCADE يحذف كل سجلاته) مع إعادة محاولة."""
    from sqlalchemy import delete, or_, select
    from sqlalchemy.exc import SQLAlchemyError

    from core.db import SessionLocal, engine
    from core.models import User

    for attempt in range(1, 4):
        try:
            async with SessionLocal() as s:
                conds = []
                if user_id is not None:
                    conds.append(User.id == user_id)
                if email:
                    conds.append(User.email == email)
                if not conds:
                    return
                await s.execute(delete(User).where(or_(*conds)))
                await s.commit()
            # تحقق
            async with SessionLocal() as s:
                left = await s.scalar(
                    select(User.id).where(or_(*conds)).limit(1)
                )
            if not left:
                print("[OK]   حُذف الحساب المؤقت")
                return
        except SQLAlchemyError as e:  # noqa: BLE001
            print(f"[WARN] محاولة تنظيف {attempt} فشلت: {type(e).__name__}")
            try:
                await engine.dispose()
            except Exception:  # noqa: BLE001
                pass
        await asyncio.sleep(2)
    print(f"[WARN] تعذّر حذف الحساب المؤقت user_id={user_id} email={email}")


async def sweep_stale_audit_users() -> None:
    """يحذف أي حسابات تدقيق قديمة عالقة من تشغيلات سابقة."""
    from sqlalchemy import delete, select
    from sqlalchemy.exc import SQLAlchemyError

    from core.db import SessionLocal, engine
    from core.models import User

    for attempt in range(1, 4):
        try:
            async with SessionLocal() as s:
                ids = list(
                    (
                        await s.execute(
                            select(User.id).where(User.email.like("audit+%@example.invalid"))
                        )
                    ).scalars()
                )
                if not ids:
                    return
                await s.execute(delete(User).where(User.id.in_(ids)))
                await s.commit()
                print(f"[OK]   حُذفت {len(ids)} حسابات تدقيق قديمة")
                return
        except SQLAlchemyError as e:  # noqa: BLE001
            print(f"[WARN] تنظيف القديم (محاولة {attempt}) فشل: {type(e).__name__}")
            try:
                await engine.dispose()
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(3)


async def main() -> int:
    base = (os.environ.get("API_BASE_URL") or "https://aldhaibot-production.up.railway.app").strip()
    stamp = int(time.time())
    email = f"audit+{stamp}@example.invalid"
    password = f"Smoke-{stamp}-Aa1"

    await sweep_stale_audit_users()

    # 1) صحة الخدمة العامة
    code, health = request(base, "GET", "/health")
    if code == 200 and isinstance(health, dict) and health.get("ready"):
        ok("health")
    else:
        fail(f"health → HTTP {code}: {health}")

    code, data = request(base, "GET", "/api/languages")
    if code == 200 and isinstance(data, list) and len(data) == 48:
        ok(f"languages ({len(data)})")
    else:
        fail(f"languages → HTTP {code}: {data}")

    code, data = request(base, "GET", "/api/courses")
    if code == 200 and isinstance(data, list) and len(data) >= 8:
        slugs = [c.get("slug") for c in data]
        ok(f"courses ({len(data)}): {', '.join(slugs)}")
    else:
        fail(f"courses → HTTP {code}: {data}")

    # 2) تسجيل حساب مؤقت
    code, reg = request(
        base,
        "POST",
        "/api/auth/register",
        body={"email": email, "password": password, "username": f"audit{stamp}"},
    )
    token = None
    user_id = None
    if code in (200, 201) and isinstance(reg, dict) and reg.get("token"):
        token = reg["token"]
        user_id = int(reg["user_id"])
        ok(f"register (user_id={user_id})")
    else:
        fail(f"register → HTTP {code}: {reg}")
        return 1

    try:
        # 3) دخول بنفس البيانات
        code, login = request(
            base, "POST", "/api/auth/login", body={"email": email, "password": password}
        )
        if code == 200 and isinstance(login, dict) and login.get("token"):
            ok("login")
        else:
            fail(f"login → HTTP {code}: {login}")

        # 4) /me
        code, me = request(base, "GET", "/api/auth/me", token=token)
        if code == 200 and isinstance(me, dict) and int(me.get("id", -1)) == user_id:
            ok("auth/me")
        else:
            fail(f"auth/me → HTTP {code}: {me}")

        # 5) المسارات
        code, paths = request(base, "GET", "/api/paths", token=token)
        if code == 200 and isinstance(paths, list) and len(paths) == 3:
            ok("paths (3)")
            for p in paths:
                if not p.get("total"):
                    fail(f"مسار بلا دروس: {p.get('slug')}")
            print("       " + " | ".join(f"{p['slug']}={p['total']}" for p in paths))
        else:
            fail(f"paths → HTTP {code}: {paths}")

        if isinstance(paths, list) and paths:
            code, one = request(base, "GET", f"/api/paths/{paths[0]['slug']}", token=token)
            if code == 200 and isinstance(one, dict) and one.get("courses"):
                ok(f"paths/{paths[0]['slug']}")
            else:
                fail(f"paths/{{slug}} → HTTP {code}: {one}")

        # 6) الدرس اليومي
        code, daily = request(base, "GET", "/api/daily", token=token)
        if code == 200 and isinstance(daily, dict) and daily.get("lesson"):
            ok(f"daily (lesson={daily['lesson'].get('title')})")
        else:
            fail(f"daily → HTTP {code}: {daily}")

        # 7) دروس الكورس التجريبي + اختباره
        code, lessons = request(
            base, "GET", "/api/courses/python-security/lessons", token=token
        )
        lesson_id = None
        if code == 200 and isinstance(lessons, list) and lessons:
            lesson_id = lessons[0].get("id")
            ok(f"courses/python-security/lessons ({len(lessons)})")
        else:
            fail(f"course lessons → HTTP {code}: {lessons}")

        if lesson_id:
            code, quiz = request(base, "GET", f"/api/lessons/{lesson_id}/quiz")
            if code == 200 and isinstance(quiz, dict) and quiz.get("questions"):
                ok(f"lesson quiz ({len(quiz['questions'])} أسئلة)")
            else:
                fail(f"lesson quiz → HTTP {code}: {quiz}")

            code, assets = request(base, "GET", f"/api/lessons/{lesson_id}/assets")
            if code == 200 and isinstance(assets, list):
                ok(f"lesson assets ({len(assets)})")
            else:
                fail(f"lesson assets → HTTP {code}: {assets}")

            code, labs = request(base, "GET", f"/api/lessons/{lesson_id}/labs")
            if code == 200 and isinstance(labs, list):
                ok(f"lesson labs ({len(labs)})")
            else:
                fail(f"lesson labs → HTTP {code}: {labs}")

            # 8) تسليم اختبار بإجابات صحيحة (من القاعدة)
            answers = await correct_answers(lesson_id)
            if not answers:
                fail("تعذّر قراءة الإجابات الصحيحة من القاعدة")
            else:
                code, result = request(
                    base,
                    "POST",
                    f"/api/lessons/{lesson_id}/attempt",
                    token=token,
                    body={"responses": {str(k): v for k, v in answers.items()}},
                )
                if (
                    code == 200
                    and isinstance(result, dict)
                    and result.get("passed") is True
                    and int(result.get("score", -1)) == 100
                ):
                    ok("attempt (score=100, passed=true)")
                else:
                    fail(f"attempt (إجابات صحيحة) → HTTP {code}: {result}")

                # 9) بعد النجاح: التقدّم والدرس التالي
                code, status = request(
                    base, "GET", "/api/courses/python-security/lessons", token=token
                )
                if code == 200 and isinstance(status, list) and status:
                    first = status[0]
                    if first.get("status") == "passed":
                        ok("تحديث التقدّم إلى passed")
                    else:
                        fail(f"التقدّم بعد النجاح = {first.get('status')}")

        # 10) نقاط المجتمع والتقدّم
        for path, name in [
            ("/api/leaderboard", "leaderboard"),
            ("/api/me/rank", "me/rank"),
            ("/api/notes", "notes"),
            ("/api/bookmarks", "bookmarks"),
            ("/api/certificates", "certificates"),
        ]:
            code, data = request(base, "GET", path, token=token)
            if code == 200:
                ok(name)
            else:
                fail(f"{name} → HTTP {code}: {data}")

        # 11) ملاحظة + إشارة مرجعية
        if lesson_id:
            code, note = request(
                base,
                "POST",
                "/api/notes",
                token=token,
                body={"lesson_id": lesson_id, "text": "ملاحظة اختبار آلي"},
            )
            if code in (200, 201):
                ok("create note")
            else:
                fail(f"create note → HTTP {code}: {note}")
            code, bm = request(
                base, "POST", f"/api/bookmarks/{lesson_id}", token=token
            )
            if code in (200, 201):
                ok("toggle bookmark")
            else:
                fail(f"bookmark → HTTP {code}: {bm}")

        # 12) مسار غير موجود يجب أن يعيد 404
        code, _ = request(base, "GET", "/api/paths/does-not-exist", token=token)
        if code == 404:
            ok("404 لمسار غير موجود")
        else:
            fail(f"مسار غير موجود أعاد {code} بدل 404")

        # 13) رفض توكن غير صالح
        code, _ = request(base, "GET", "/api/auth/me", token="invalid.token.value")
        if code == 401:
            ok("رفض التوكن غير الصالح (401)")
        else:
            fail(f"توكن غير صالح أعاد {code} بدل 401")

        # 14) Mini App
        code, page = request(base, "GET", "/app")
        if code == 200:
            ok("/app (Mini App)")
        else:
            fail(f"/app → HTTP {code}")
    finally:
        await cleanup(user_id, email)

    print()
    print(f"نجح: {len(OKS)} — فشل: {len(FAILS)}")
    if FAILS:
        print("المشاكل:")
        for f in FAILS:
            print(f"  [خطأ] {f}")
        return 1
    print("كل فحوص API ناجحة ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
