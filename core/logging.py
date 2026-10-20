# -*- coding: utf-8 -*-
"""تهيئة السجلّات (Logging) بشكل موحّد لكل الخدمات."""
from __future__ import annotations

import logging
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

from core.config import settings

_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"

# حد Railway: 500 رسالة/ثانية. نخنق الرسائل المتكررة لنفس النص.
_MAX_REPEATS = 3
_REPEAT_WINDOW = 60.0  # ثانية


class _ThrottleFilter(logging.Filter):
    """يمنع تكرار نفس الرسالة أكثر من _MAX_REPEATS في نافذة زمنية."""

    def __init__(self) -> None:
        super().__init__()
        self._seen: dict[tuple[str, str], list[float]] = {}
        self._lock = threading.Lock()

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            key = (record.name, record.getMessage()[:200])
        except Exception:  # noqa: BLE001
            return True
        now = time.monotonic()
        with self._lock:
            times = self._seen.setdefault(key, [])
            times[:] = [t for t in times if now - t < _REPEAT_WINDOW]
            if len(times) >= _MAX_REPEATS:
                return False
            times.append(now)
            # تنظيف دوري للمفاتيح القديمة
            if len(self._seen) > 500:
                for k in list(self._seen):
                    if not [t for t in self._seen[k] if now - t < _REPEAT_WINDOW]:
                        self._seen.pop(k, None)
        return True


def setup_logging() -> None:
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    formatter = logging.Formatter(_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")

    # على ويندوز الترميز الافتراضي للطرفية (charmap/cp1256) لا يدعم الرموز
    # التعبيرية → يفشل logging وتفقد السطر بالكامل. نفرض UTF-8 مع بديل.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass

    root = logging.getLogger()
    root.handlers.clear()

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    stream.addFilter(_ThrottleFilter())
    root.addHandler(stream)

    # سجل دوّار للتشغيل المستمر (24/7): 5 ملفات × 5MB
    if settings.LOG_DIR:
        try:
            log_dir = Path(settings.LOG_DIR)
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                log_dir / "bot.log",
                maxBytes=5 * 1024 * 1024,
                backupCount=5,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            file_handler.addFilter(_ThrottleFilter())
            root.addHandler(file_handler)
        except OSError:
            pass

    root.setLevel(level)
    # المصادر الصاخبة: نخنقها أكثر
    for noisy in ("httpx", "httpcore", "telegram.ext.Updater", "telegram.ext.Application",
                  "apscheduler", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
