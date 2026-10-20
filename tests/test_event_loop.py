# -*- coding: utf-8 -*-
"""اختبارات منع تعارض حلقات الأحداث (attached to a different loop).

السبب الجذري: `asyncio.run(init_db())` ينشئ حلقة، ثم `run_polling()` ينشئ
حلقة أخرى — ومحرّك SQLAlchemy مربوط بالأولى، فتفشل كل عملية كتابة.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOT = ROOT / "app" / "bot.py"


def _src() -> str:
    return BOT.read_text(encoding="utf-8")


def _run_body() -> str:
    return _src().split("def _run()")[1].split("def _idle_loop")[0]


def _post_init_body() -> str:
    return _src().split("async def post_init")[1].split("async def private_only")[0]


class TestNoDatabaseInSeparateLoop:
    """عمليات القاعدة يجب أن تكون داخل حلقة التطبيق."""

    def test_run_does_not_init_db_in_its_own_loop(self) -> None:
        body = _run_body()
        assert "asyncio.run(init_db())" not in body, (
            "init_db must not run in its own event loop"
        )

    def test_post_init_initialises_the_database(self) -> None:
        body = _post_init_body()
        assert "await init_db()" in body, "post_init must initialise the database"

    def test_post_init_seeds_the_database(self) -> None:
        body = _post_init_body()
        assert "ensure_seeded" in body

    def test_database_close_is_in_post_shutdown(self) -> None:
        body = _src().split("async def post_shutdown")[1].split("class _ConflictAwareUpdater")[0]
        assert "await close_db()" in body, (
            "the engine must be disposed inside the application loop"
        )

    def test_run_does_not_close_db_in_its_own_loop(self) -> None:
        body = _run_body()
        assert "asyncio.run(close_db())" not in body

    def test_only_telegram_calls_use_asyncio_run(self) -> None:
        """asyncio.run مسموح فقط لتيليجرام (لا قاعدة بيانات)."""
        allowed = {"_validate_token"}
        for match in re.finditer(r"asyncio\.run\((_?\w+)\(", _src()):
            fn = match.group(1)
            assert fn in allowed, f"asyncio.run({fn}) is not allowed here"


class TestDiagHasNoEventLoop:
    """/diag يعمل من خيط بلا حلقة."""

    def test_diag_does_not_use_asyncio_run(self) -> None:
        body = _src().split("def _diag_database")[1].split("def _startup_banner")[0]
        assert "asyncio.run" not in body, (
            "the diagnostic must not create an event loop from the health thread"
        )

    def test_diag_uses_a_tcp_probe(self) -> None:
        assert "def _probe_tcp" in _src()
        body = _src().split("def _diag_database")[1].split("def _startup_banner")[0]
        assert "_probe_tcp" in body

    def test_diag_reports_last_init(self) -> None:
        body = _src().split("def _diag_database")[1].split("def _startup_banner")[0]
        assert "last_init_ok" in body
        assert "persistent" in body


class TestReadyFlag:
    def test_ready_is_set_after_initialisation(self) -> None:
        body = _post_init_body()
        assert '_db_state["ready"] = True' in body

    def test_db_state_is_shared(self) -> None:
        assert "_db_state" in _src()
        assert "def _probe_tcp" in _src()


class TestAdminsConfigured:
    """ADMIN_IDS فارغ = أوامر المشرف لا تعمل لأي مستخدم."""

    def test_startup_warns_when_admins_missing(self) -> None:
        body = _post_init_body()
        assert "ADMIN_IDS" in body

    def test_diag_reports_admins_configured(self) -> None:
        assert '"admins_configured"' in _src()


class TestLiveStats:
    """عدّاد الرسائل — دليل مباشر على أن البوت يستقبل."""

    def test_counter_increments(self) -> None:
        from app.bot import _bump_update_counter, _live_stats

        before = _live_stats["updates"]
        _bump_update_counter()
        assert _live_stats["updates"] == before + 1
        assert _live_stats["last_update"] > 0

    def test_diag_exposes_the_counter(self) -> None:
        assert '"updates_received"' in _src()
        assert "_count_update" in _src()


class TestTcpProbe:
    def test_probe_returns_false_for_a_closed_port(self) -> None:
        import socket

        from app.bot import _probe_tcp

        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            free_port = s.getsockname()[1]
        assert _probe_tcp("127.0.0.1", free_port, timeout=1.0) is False

    def test_probe_returns_true_for_a_listening_port(self) -> None:
        import socket
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *a):
                return

        srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            from app.bot import _probe_tcp

            assert _probe_tcp("127.0.0.1", port, timeout=3.0) is True
        finally:
            srv.shutdown()

    def test_db_host_port_parsing(self) -> None:
        from app.bot import _db_host_port

        import core.db as db

        original = db._DATABASE_URL
        try:
            db._DATABASE_URL = "postgresql+asyncpg://u:p@db.railway.internal:5432/railway"
            host, port = _db_host_port()
            assert host == "db.railway.internal"
            assert port == 5432

            db._DATABASE_URL = "sqlite+aiosqlite:///./data/app.db"
            assert _db_host_port() == ("", 0)
        finally:
            db._DATABASE_URL = original
