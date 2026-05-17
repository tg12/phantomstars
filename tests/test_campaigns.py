"""Tests for campaign detection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from phantomstars.campaigns import detect_campaigns
from phantomstars.models import EngagementEvent, SuspicionScore

SCAN_DATE = "2026-05-17"
_T0 = datetime(2026, 5, 17, 10, 0, 0, tzinfo=UTC)


def _score(login: str, composite: float = 0.80) -> SuspicionScore:
    return SuspicionScore(
        login=login,
        account_age_score=0.9,
        profile_score=0.8,
        repo_pattern_score=0.8,
        activity_score=0.7,
        composite=composite,
        classification="likely_fake",
        campaign_id=None,
        scan_date=SCAN_DATE,
        account_created_at="2026-05-10",
    )


def _ev(login: str, repo: str, minutes_offset: int = 0) -> EngagementEvent:
    return EngagementEvent(
        user_login=login,
        repo_full_name=repo,
        kind="star",
        occurred_at=_T0 + timedelta(minutes=minutes_offset),
    )


def test_campaign_detected_within_window() -> None:
    logins = ["bot1", "bot2", "bot3", "bot4"]
    scores = {login: _score(login) for login in logins}
    events = [_ev(login, "owner/repo", i * 10) for i, login in enumerate(logins)]
    result = detect_campaigns(events, scores)
    assert len(result) == 4
    assert len(set(result.values())) == 1  # all in same campaign


def test_no_campaign_below_min_size() -> None:
    logins = ["bot1", "bot2", "bot3"]  # below MIN_CAMPAIGN_SIZE=4
    scores = {login: _score(login) for login in logins}
    events = [_ev(login, "owner/repo", i * 5) for i, login in enumerate(logins)]
    result = detect_campaigns(events, scores)
    assert result == {}


def test_accounts_outside_window_not_linked() -> None:
    scores = {"bot1": _score("bot1"), "bot2": _score("bot2")}
    # 5 hours apart, window is 3 hours
    events = [_ev("bot1", "owner/repo", 0), _ev("bot2", "owner/repo", 300)]
    result = detect_campaigns(events, scores)
    assert result == {}


def test_clean_accounts_excluded_from_campaign() -> None:
    scores = {
        "bot1": _score("bot1", 0.80),
        "bot2": _score("bot2", 0.80),
        "bot3": _score("bot3", 0.80),
        "bot4": _score("bot4", 0.80),
        "legit": _score("legit", 0.10),  # clean
    }
    events = [_ev(login, "owner/repo", i * 5) for i, login in enumerate(scores)]
    result = detect_campaigns(events, scores)
    assert "legit" not in result


def test_separate_repos_can_link_accounts() -> None:
    logins = ["b1", "b2", "b3", "b4"]
    scores = {login: _score(login) for login in logins}
    # b1+b2 on repo-a, b2+b3+b4 on repo-b — union-find should link all
    events = [
        _ev("b1", "x/repo-a", 0),
        _ev("b2", "x/repo-a", 10),
        _ev("b2", "x/repo-b", 20),
        _ev("b3", "x/repo-b", 30),
        _ev("b4", "x/repo-b", 40),
    ]
    result = detect_campaigns(events, scores)
    assert len(result) == 4
    assert len(set(result.values())) == 1
