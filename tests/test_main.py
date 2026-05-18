"""Tests for targeted scan behavior."""

from __future__ import annotations

import pytest

from phantomstars.main import _build_repo_reports, _collect_repo_events, _parse_target_repo
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

    def get_recent_engagement(self, repo_full_name: str) -> list[EngagementEvent]:
        response = self.responses[self.calls]
        self.calls += 1
        return response


def test_build_repo_reports_includes_clean_target_when_explicitly_scanned() -> None:
    reports = _build_repo_reports(
        final_scores=[],
        flat_events=[_event("real-user", "owner/repo")],
        scan_date=SCAN_DATE,
        scanned_repos={"owner/repo"},
    )

    assert len(reports) == 1
    assert reports[0].full_name == "owner/repo"
    assert reports[0].classification == "clean"
    assert reports[0].fakeness_ratio == 0.0


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
        scanned_repos={"owner/repo"},
    )

    assert len(reports) == 1
    assert reports[0].likely_fake == 1
    assert reports[0].suspicious == 1
    assert reports[0].campaign_count == 1
    assert reports[0].fakeness_ratio == 0.333


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

    events = _collect_repo_events(client, "owner/repo", targeted_mode=True)

    assert len(events) == 1
    assert client.calls == 2
