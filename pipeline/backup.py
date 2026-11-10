# -*- coding: utf-8 -*-
"""نسخ احتياطي لبيانات المستخدمين (JSON مضغوط) واستعادتها.

المحتوى التعليمي (الدروس/الاختبارات) يمكن توليده من جديد، أما **تقدّم
المستخدمين** وملاحظاتهم وشهاداتهم فلا يمكن تعويضه. لذلك تُنسخ هذه الجداول
وحدها: حجمها صغير (كيلوبايتات) ويمكن إرسالها إلى المشرف عبر تلجرام.

الاستعادة: `python -m scripts.restore_backup --file backup.json.gz`
"""
from __future__ import annotations

import base64
import datetime as dt
import decimal
import gzip
import json
from typing import Any, Iterator

from sqlalchemy import select, text

from core.db import SessionLocal, engine
from core.logging import get_logger
from core.models import (
    Answer,
    Attempt,
    Bookmark,
    Certificate,
    CodeFavorite,
    CodeShare,
    DailyAssignment,
    LabInstance,
    LessonRating,
    LessonTimeLog,
    Note,
    PathCertificate,
    Progress,
    Reminder,
    ReviewSchedule,
    Submission,
    User,
    UserBadge,
    XpEvent,
)

log = get_logger("pipeline.backup")

BACKUP_VERSION = 1

# ترتيب الاعتماد: المستخدم أولا، ثم الجداول التي تشير إليه.
BACKUP_MODELS = [
    User,
    Progress,
    Attempt,
    Answer,
    Note,
    Bookmark,
    Certificate,
    PathCertificate,
    XpEvent,
    UserBadge,
    ReviewSchedule,
    LessonTimeLog,
    LessonRating,
    CodeFavorite,
    CodeShare,
    DailyAssignment,
    Reminder,
    Submission,
    LabInstance,
]


def _jsonable(value: Any) -> Any:
    """يحوّل قيم قاعدة البيانات إلى JSON (التواريخ بصيغة ISO)."""
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"__b64__": base64.b64encode(bytes(value)).decode("ascii")}
    return value


def _restore_value(col, value: Any) -> Any:
    """يعيد القيمة إلى نوع العمود قبل الإدراج."""
    if value is None:
        return None
    if isinstance(value, dict) and set(value) == {"__b64__"}:
        return base64.b64decode(value["__b64__"])
    try:
        py = col.type.python_type
    except (NotImplementedError, AttributeError):
        return value
    try:
        if py is dt.datetime and isinstance(value, str):
            return dt.datetime.fromisoformat(value)
        if py is dt.date and isinstance(value, str):
            return dt.date.fromisoformat(value)
        if py is dt.time and isinstance(value, str):
            return dt.time.fromisoformat(value)
        if py is decimal.Decimal:
            return decimal.Decimal(str(value))
    except (TypeError, ValueError):
        return value
    return value


def _chunks(rows: list[dict], size: int) -> Iterator[list[dict]]:
    for i in range(0, len(rows), size):
        yield rows[i : i + size]


def backup_filename(now: dt.datetime | None = None) -> str:
    stamp = (now or dt.datetime.now(dt.timezone.utc)).strftime("%Y%m%d-%H%M")
    return f"academy-backup-{stamp}.json.gz"


async def dump_user_data() -> tuple[bytes, dict[str, int]]:
    """يبني نسخة مضغوطة من بيانات المستخدمين ويعيد (البايتات، عدد الصفوف)."""
    payload: dict[str, Any] = {
        "version": BACKUP_VERSION,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "tables": {},
    }
    counts: dict[str, int] = {}
    async with SessionLocal() as session:
        for model in BACKUP_MODELS:
            cols = [c.key for c in model.__table__.columns]
            rows = list((await session.execute(select(model))).scalars().all())
            payload["tables"][model.__tablename__] = [
                {c: _jsonable(getattr(row, c, None)) for c in cols} for row in rows
            ]
            counts[model.__tablename__] = len(rows)
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return gzip.compress(raw, 9), counts


def load_backup(blob: bytes) -> dict[str, Any]:
    """يفكّ ضغط النسخة ويتحقق من بنيتها."""
    if blob[:2] == b"\x1f\x8b":
        blob = gzip.decompress(blob)
    payload = json.loads(blob.decode("utf-8"))
    if not isinstance(payload, dict) or "tables" not in payload:
        raise ValueError("ملف النسخة الاحتياطية غير صالح")
    return payload


async def _would_insert(session, model, values: list[dict]) -> int:
    """عدد الصفوف التي ستُضاف فعلا (معرّفاتها غير موجودة)."""
    from sqlalchemy import func

    ids = [v.get("id") for v in values if v.get("id") is not None]
    if not ids:
        return len(values)
    existing = 0
    for chunk in _chunks(ids, 500):
        existing += int(
            await session.scalar(
                select(func.count())
                .select_from(model)
                .where(model.__table__.c.id.in_(chunk))
            )
            or 0
        )
    return max(0, len(values) - existing)


async def restore_payload(payload: dict[str, Any], *, dry_run: bool = False) -> dict[str, int]:
    """يستعيد الصفوف الناقصة فقط (لا يمسّ الصفوف الموجودة)."""
    if engine.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert
    else:
        from sqlalchemy.dialects.sqlite import insert as dialect_insert

    counts: dict[str, int] = {}
    async with SessionLocal() as session:
        for model in BACKUP_MODELS:
            table = model.__tablename__
            rows = payload.get("tables", {}).get(table) or []
            if not rows:
                counts[table] = 0
                continue
            cols = {c.key: c for c in model.__table__.columns}
            values = [
                {k: _restore_value(cols[k], v) for k, v in row.items() if k in cols}
                for row in rows
            ]

            if dry_run:
                # لا نكتب شيئا: نحسب الصفوف التي ستُضاف فقط.
                counts[table] = await _would_insert(session, model, values)
                continue

            inserted = 0
            try:
                async with session.begin_nested():
                    for chunk in _chunks(values, 500):
                        stmt = (
                            dialect_insert(model)
                            .values(chunk)
                            .on_conflict_do_nothing()
                        )
                        result = await session.execute(stmt)
                        if isinstance(result.rowcount, int) and result.rowcount > 0:
                            inserted += result.rowcount
                counts[table] = inserted or 0
            except Exception as e:  # noqa: BLE001
                # صف يشير إلى درس/اختبار غير موجود (محتوى أُعيد توليده بمعرّفات
                # مختلفة) يُفشل الدفعة كلها، لذا نعيد المحاولة صفا صفا.
                log.warning("تعذّر استعادة %s دفعة واحدة (%s) — محاولة فردية", table, e)
                inserted = 0
                for row in values:
                    try:
                        async with session.begin_nested():
                            result = await session.execute(
                                dialect_insert(model)
                                .values([row])
                                .on_conflict_do_nothing()
                            )
                            if isinstance(result.rowcount, int) and result.rowcount > 0:
                                inserted += result.rowcount
                    except Exception:  # noqa: BLE001
                        continue
                counts[table] = inserted

        if not dry_run and engine.dialect.name == "postgresql":
            for model in BACKUP_MODELS:
                table = model.__tablename__
                try:
                    await session.execute(
                        text(
                            f"SELECT setval(pg_get_serial_sequence('{table}','id'),"
                            f" COALESCE((SELECT MAX(id) FROM {table}), 1))"
                        )
                    )
                except Exception as e:  # noqa: BLE001
                    log.debug("تعذّر ضبط تسلسل %s: %s", table, e)

        if not dry_run:
            await session.commit()
    return counts


async def table_counts() -> dict[str, int]:
    """أعداد الصفوف الحالية (لعرضها مع النسخة)."""
    from sqlalchemy import func

    out: dict[str, int] = {}
    async with SessionLocal() as session:
        for model in BACKUP_MODELS:
            out[model.__tablename__] = int(
                await session.scalar(select(func.count()).select_from(model)) or 0
            )
    return out
