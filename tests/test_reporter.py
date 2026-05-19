"""Tests for README dashboard reporting."""

from __future__ import annotations

from phantomstars.reporter import _build_daily_table


def test_build_daily_table_counts_new_fakes_from_prior_likely_fake_only() -> None:
    records = [
        {"scan_date": "2026-05-01", "login": "repeat-bot", "classification": "likely_fake"},
        {"scan_date": "2026-05-02", "login": "repeat-bot", "classification": "suspicious"},
        {"scan_date": "2026-05-02", "login": "new-bot", "classification": "likely_fake"},
        {"scan_date": "2026-05-02", "login": "suspicious-only", "classification": "suspicious"},
    ]

    table = _build_daily_table(records)

    assert "| 2026-05-02 | 3 | 1 | 2 | 0 | 1 |" in table


def test_build_daily_table_preserves_seen_history_outside_visible_window() -> None:
    records = [
        {"scan_date": f"2026-04-{day:02d}", "login": f"bot-{day}", "classification": "likely_fake"}
        for day in range(1, 31)
    ]
    records.append(
        {"scan_date": "2026-05-01", "login": "bot-1", "classification": "likely_fake"}
    )

    table = _build_daily_table(records)

    assert "| 2026-05-01 | 1 | 1 | 0 | 0 | 0 |" in table
