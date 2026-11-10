# -*- coding: utf-8 -*-
"""اختبار أدوات سكربت الحمل (بلا شبكة)."""
from __future__ import annotations

from scripts.load_test import Stats, _attempt_responses


class TestStats:
    def test_percentile_bounds(self) -> None:
        values = [10.0, 20.0, 30.0, 40.0, 50.0]
        assert Stats.percentile(values, 0) == 10.0
        assert Stats.percentile(values, 100) == 50.0
        assert Stats.percentile(values, 50) == 30.0

    def test_empty_percentile(self) -> None:
        assert Stats.percentile([], 95) == 0.0

    def test_table_aggregates_and_counts_errors(self) -> None:
        stats = Stats()
        stats.add("daily", 200, 0.100)
        stats.add("daily", 200, 0.300)
        stats.add("daily", 500, 0.200, "boom")
        stats.add("paths", 0, 0.050, "timeout")
        rows = {row["endpoint"]: row for row in stats.table()}
        assert rows["daily"]["n"] == 3
        assert rows["daily"]["bad"] == 1
        assert rows["daily"]["codes"][200] == 2
        assert rows["daily"]["p50"] > 0
        assert rows["paths"]["bad"] == 1
        assert len(stats.errors) == 2


class TestAttemptResponses:
    def test_picks_first_option_per_question(self) -> None:
        quiz = {
            "questions": [
                {"id": 11, "options": [{"id": 101}, {"id": 102}]},
                {"id": 12, "options": [{"id": 201}]},
                {"id": 13, "options": []},
            ]
        }
        assert _attempt_responses(quiz) == {"11": [101], "12": [201]}

    def test_handles_bad_payload(self) -> None:
        assert _attempt_responses(None) == {}
        assert _attempt_responses({"questions": "x"}) == {}
