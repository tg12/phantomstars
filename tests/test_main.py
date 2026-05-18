"""Tests for targeted scan behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from phantomstars.config import LIFETIME_ANALYSIS_MODE, RECENT_ANALYSIS_MODE
from phantomstars.main import (
    _build_repo_reports,
    _collect_repo_events,
    _load_prior_likely_fake_history,
    _parse_analysis_mode,
    _parse_target_repo,
)
from phantomstars.models import EngagementEvent, SuspicionScore

SCAN_DATE = "2026-05-18"


def _score(
    login: str,
    repo: str,
    *,
    classification: str = "likely_fake",
    campaign_id: str | None = None,
) -> SuspicionScore:
    return SuspicionScore(
        login=login,
        account_age_score=0.9,
        profile_score=0.8,
        repo_pattern_score=0.8,
        activity_score=0.7,
        composite=0.8,
        classification=classification,  # type: ignore[arg-type]
        analysis_mode=RECENT_ANALYSIS_MODE,
        campaign_id=campaign_id,
        scan_date=SCAN_DATE,
        account_created_at="2026-05-10",
        target_repos=(repo,),
    )


def _event(login: str, repo: str) -> EngagementEvent:
    return EngagementEvent(
        user_login=login,
        repo_full_name=repo,
        kind="star",
        occurred_at=None,
    )


class RetryClient:
    def __init__(self, responses: list[list[EngagementEvent]]) -> None:
        self.responses = responses
        self.calls = 0
        self.lifetime_calls = 0

    def get_recent_engagement(self, repo_full_name: str) -> list[EngagementEvent]:
        response = self.responses[self.calls]
        self.calls += 1
        return response

    def get_lifetime_engagement(self, repo_full_name: str) -> list[EngagementEvent]:
        self.lifetime_calls += 1
        return self.responses[0]


def test_build_repo_reports_includes_clean_target_when_explicitly_scanned() -> None:
    reports = _build_repo_reports(
        final_scores=[],
        flat_events=[_event("real-user", "owner/repo")],
        scan_date=SCAN_DATE,
        analysis_mode=RECENT_ANALYSIS_MODE,
        scanned_repos={"owner/repo"},
    )

    assert len(reports) == 1
    assert reports[0].full_name == "owner/repo"
    assert reports[0].classification == "clean"
    assert reports[0].analysis_mode == RECENT_ANALYSIS_MODE
    assert reports[0].fakeness_ratio == 0.0
    assert reports[0].known_likely_fake == 0
    assert reports[0].repeat_offenders == 0


def test_build_repo_reports_uses_flagged_accounts_for_ratios() -> None:
    reports = _build_repo_reports(
        final_scores=[
            _score("bot-1", "owner/repo", campaign_id="c-1"),
            _score("user-2", "owner/repo", classification="suspicious"),
        ],
        flat_events=[
            _event("bot-1", "owner/repo"),
            _event("user-2", "owner/repo"),
            _event("user-3", "owner/repo"),
        ],
        scan_date=SCAN_DATE,
        analysis_mode=RECENT_ANALYSIS_MODE,
        scanned_repos={"owner/repo"},
        historical_likely_fake_dates={
            "bot-1": {"2026-05-16", "2026-05-17"},
            "user-3": {"2026-05-17"},
        },
    )

    assert len(reports) == 1
    assert reports[0].likely_fake == 1
    assert reports[0].suspicious == 1
    assert reports[0].campaign_count == 1
    assert reports[0].fakeness_ratio == 0.333
    assert reports[0].known_likely_fake == 2
    assert reports[0].known_likely_fake_ratio == 0.667
    assert reports[0].repeat_offenders == 1


def test_load_prior_likely_fake_history_filters_non_likely_fake(tmp_path: Path) -> None:
    ledger = tmp_path / "suspects.jsonl"
    ledger.write_text(
        "\n".join(
            [
                '{"login":"bot-1","classification":"likely_fake","scan_date":"2026-05-16"}',
                '{"login":"bot-1","classification":"likely_fake","scan_date":"2026-05-17"}',
                '{"login":"user-2","classification":"suspicious","scan_date":"2026-05-17"}',
                '{"login":"bot-3","classification":"likely_fake","scan_date":"2026-05-18"}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    history = _load_prior_likely_fake_history(ledger)

    assert history == {
        "bot-1": {"2026-05-16", "2026-05-17"},
        "bot-3": {"2026-05-18"},
    }


def test_parse_target_repo_reads_owner_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PHANTOMSTARS_TARGET_REPO", "owner/repo")
    assert _parse_target_repo() == "owner/repo"


def test_parse_target_repo_rejects_invalid_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PHANTOMSTARS_TARGET_REPO", "not-a-repo")
    with pytest.raises(ValueError, match="owner/repo"):
        _parse_target_repo()


def test_parse_target_repo_returns_none_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PHANTOMSTARS_TARGET_REPO", raising=False)
    assert _parse_target_repo() is None


def test_collect_repo_events_retries_once_in_targeted_mode() -> None:
    client = RetryClient([[], [_event("user-1", "owner/repo")]])

    events = _collect_repo_events(
        client,
        "owner/repo",
        targeted_mode=True,
        analysis_mode=RECENT_ANALYSIS_MODE,
    )

    assert len(events) == 1
    assert client.calls == 2


def test_collect_repo_events_uses_lifetime_path_when_requested() -> None:
    client = RetryClient([[_event("user-1", "owner/repo")]])

    events = _collect_repo_events(
        client,
        "owner/repo",
        targeted_mode=True,
        analysis_mode=LIFETIME_ANALYSIS_MODE,
    )

    assert len(events) == 1
    assert client.lifetime_calls == 1
    assert client.calls == 0


def test_parse_analysis_mode_defaults_to_recent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PHANTOMSTARS_REQUEST_DEPTH", raising=False)
    assert _parse_analysis_mode() == RECENT_ANALYSIS_MODE


def test_parse_analysis_mode_reads_lifetime_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PHANTOMSTARS_REQUEST_DEPTH", "lifetime-request")
    assert _parse_analysis_mode() == LIFETIME_ANALYSIS_MODE
