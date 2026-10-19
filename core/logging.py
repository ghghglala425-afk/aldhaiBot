# -*- coding: utf-8 -*-
"""تهيئة السجلّات (Logging) بشكل موحّد لكل الخدمات."""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from core.config import settings

_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def setup_logging() -> None:
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    formatter = logging.Formatter(_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.handlers.clear()

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
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
            root.addHandler(file_handler)
        except OSError:
            pass

    root.setLevel(level)
    for noisy in ("httpx", "httpcore", "telegram.ext.Updater"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
