"""Tests for maintainer-facing notification content."""

from __future__ import annotations

from phantomstars.config import RECENT_ANALYSIS_MODE
from phantomstars.models import RepoReport, SuspicionScore
from phantomstars.notifier import _comment_body, _issue_body


def _report(*, event_sample_complete: bool) -> RepoReport:
    return RepoReport(
        full_name="owner/repo",
        total_scanned=12,
        likely_fake=6,
        suspicious=3,
        fakeness_ratio=0.5,
        known_likely_fake=2,
        known_likely_fake_ratio=0.167,
        repeat_offenders=1,
        allowlisted_excluded=2,
        classification="likely_fake",
        campaign_count=1,
        analysis_mode=RECENT_ANALYSIS_MODE,
        scan_date="2026-05-19",
        discovery_sources=("github_search_recent", "reddit_osinttools"),
        event_sample_complete=event_sample_complete,
    )


def _suspect(login: str) -> SuspicionScore:
    return SuspicionScore(
        login=login,
        account_age_score=0.9,
        profile_score=0.8,
        repo_pattern_score=0.8,
        activity_score=0.0,
        composite=0.8,
        classification="likely_fake",
        analysis_mode=RECENT_ANALYSIS_MODE,
        campaign_id="c-1234abcd",
        scan_date="2026-05-19",
        account_created_at="2026-05-15",
        target_repos=("owner/repo",),
    )


def test_issue_body_mentions_discovery_sources_allowlist_and_capped_coverage() -> None:
    body = _issue_body(_report(event_sample_complete=False), [_suspect("bot-1")])

    assert "Allowlisted accounts excluded | 2" in body
    assert "github_search_recent, reddit_osinttools" in body
    assert "capped by the recent-events API limit" in body
    assert "exclude accounts on the current false-positive allowlist" in body
    assert "for information only" in body.lower()
    assert "no action is required" in body.lower()


def test_comment_body_mentions_complete_coverage_when_not_capped() -> None:
    body = _comment_body(_report(event_sample_complete=True), [_suspect("bot-1")])

    assert "Event coverage | complete" in body
    assert "Discovery sources | github_search_recent, reddit_osinttools" in body
