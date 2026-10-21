# -*- coding: utf-8 -*-
"""تهيئة الاختبارات: قاعدة SQLite مؤقتة + إعدادات آمنة (بلا شبكة/تنفيذ)."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_tmp = Path(tempfile.gettempdir()) / "cyber_academy_tests"
_tmp.mkdir(parents=True, exist_ok=True)
_db_file = _tmp / "test.db"

os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_db_file.as_posix()}")
os.environ.setdefault("AI_API_KEY", "test-key")
os.environ.setdefault("AI_BASE_URL", "http://localhost:1234/v1")
os.environ.setdefault("AI_MODEL", "test-model")
os.environ.setdefault("VERIFY_EXEC", "0")
os.environ.setdefault("GEN_ENRICH_ATLAS", "0")
os.environ["DISABLE_SQLALCHEMY_CEXT"] = "1"
os.environ["TEST_DB_FILE"] = str(_db_file)


@pytest.fixture(autouse=True)
def _reset_sandbox_state():
    """يمنع تسرّب طابور/قاطع دائرة التنفيذ بين الاختبارات."""
    from pipeline import sandbox_runner as sb

    sb._reset_exec_state()
    yield
    sb._reset_exec_state()
