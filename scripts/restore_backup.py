# -*- coding: utf-8 -*-
"""استعادة نسخة احتياطية من بيانات المستخدمين.

الاستخدام داخل الحاوية:
    python -m scripts.restore_backup --file /app/academy-backup-20260101-0310.json.gz
    python -m scripts.restore_backup --file backup.json.gz --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from core.db import close_db, init_db
from pipeline.backup import load_backup, restore_payload


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="استعادة نسخة احتياطية للمستخدمين")
    parser.add_argument("--file", required=True, help="مسار ملف .json.gz")
    parser.add_argument(
        "--dry-run", action="store_true", help="فحص فقط بلا كتابة في قاعدة البيانات"
    )
    return parser.parse_args()


async def _main(args: argparse.Namespace) -> int:
    path = Path(args.file)
    if not path.exists():
        print(f"❌ الملف غير موجود: {path}")
        return 2
    payload = load_backup(path.read_bytes())
    await init_db()
    try:
        counts = await restore_payload(payload, dry_run=args.dry_run)
    finally:
        await close_db()
    total = sum(v for v in counts.values() if v > 0)
    for table, n in counts.items():
        if n:
            print(f"  {table}: {n}")
    if args.dry_run:
        print(f"🔎 فحص فقط (بلا كتابة) — صفوف قابلة للاستعادة: {total}")
    else:
        print(f"✅ اكتملت الاستعادة — صفوف مضافة: {total}")
    return 0


def main() -> None:
    sys.exit(asyncio.run(_main(_parse_args())))


if __name__ == "__main__":
    main()
