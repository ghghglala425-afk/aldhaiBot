# -*- coding: utf-8 -*-
"""قفل النسخة الواحدة وكاشف التعارض: لا نسختان تستقبلان الرسائل معا."""
from __future__ import annotations

import asyncio

import pytest
from telegram.error import Conflict, NetworkError

from app import bot
from core import instance_lock
from core.config import settings


def _reset_conflict_state() -> None:
    bot._conflict_state.update({"count": 0, "notified": False, "first_at": 0.0})


def test_lock_key_is_stable_and_fits_bigint(monkeypatch):
    monkeypatch.setattr(settings, "BOT_TOKEN", "123456:abcdef")
    first = instance_lock.lock_key()
    second = instance_lock.lock_key()
    assert first == second
    assert -(2**63) <= first < 2**63


def test_lock_is_skipped_on_sqlite():
    from core.db import engine

    if engine.url.get_backend_name() == "postgresql":
        pytest.skip("الاختبار خاص بمسار SQLite المحلي")

    async def run():
        assert await instance_lock.acquire_polling_lock() is True
        await instance_lock.release_polling_lock()

    asyncio.run(run())


def test_lock_can_be_disabled(monkeypatch):
    monkeypatch.setattr(settings, "POLLING_LOCK_ENABLED", False)
    assert asyncio.run(instance_lock.acquire_polling_lock()) is True


def test_transient_conflict_is_a_warning_not_an_error(monkeypatch):
    _reset_conflict_state()
    notified = []
    monkeypatch.setattr(bot, "_notify_admins_conflict", lambda: notified.append(1))

    bot._updater_error(Conflict("Conflict: terminated by other getUpdates request"))

    assert bot._conflict_state["count"] == 1
    assert bot._conflict_state["first_at"] > 0
    assert bot._conflict_state["notified"] is False
    assert notified == []  # لا إزعاج للمشرف بسبب تعارض إعادة النشر


def test_persistent_conflict_alerts_once(monkeypatch):
    _reset_conflict_state()
    notified = []
    monkeypatch.setattr(bot, "_notify_admins_conflict", lambda: notified.append(1))
    monkeypatch.setattr(bot, "_CONFLICT_ALERT_AFTER", 0.0)

    bot._updater_error(Conflict("still conflicting"))
    bot._updater_error(Conflict("still conflicting"))

    assert notified == [1]
    assert bot._conflict_state["notified"] is True


def test_network_error_resets_conflict_state(monkeypatch):
    _reset_conflict_state()
    monkeypatch.setattr(bot, "_notify_admins_conflict", lambda: None)
    bot._updater_error(Conflict("transient"))
    assert bot._conflict_state["first_at"] > 0

    bot._updater_error(NetworkError("network hiccup"))

    assert bot._conflict_state == {"count": 0, "notified": False, "first_at": 0.0}
