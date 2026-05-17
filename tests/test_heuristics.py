"""Tests for the scoring engine."""
from __future__ import annotations

import pytest
from phantomstars.heuristics import score_user
from phantomstars.models import UserProfile

SCAN_DATE = "2026-05-17"


def test_clean_profile_scores_low(clean_profile: UserProfile) -> None:
    result = score_user(clean_profile, SCAN_DATE)
    assert result.classification == "clean"
    assert result.composite < 0.45


def test_bot_profile_scores_likely_fake(bot_profile: UserProfile) -> None:
    result = score_user(bot_profile, SCAN_DATE)
    assert result.classification == "likely_fake"
    assert result.composite >= 0.75


def test_scan_date_preserved(clean_profile: UserProfile) -> None:
    result = score_user(clean_profile, SCAN_DATE)
    assert result.scan_date == SCAN_DATE


def test_campaign_id_is_none_by_default(bot_profile: UserProfile) -> None:
    result = score_user(bot_profile, SCAN_DATE)
    assert result.campaign_id is None


def test_composite_is_weighted_sum(make_profile) -> None:  # type: ignore[no-untyped-def]
    # Account with only age signal: very new, but complete profile
    profile = make_profile(
        login="newdev",
        age_days=1,
        followers=100,
        following=80,
        bio="Engineer",
        location="Berlin",
        company="ACME",
        contribution_count=50,
        total_repo_count=5,
        fork_repo_count=1,
    )
    result = score_user(profile, SCAN_DATE)
    # Age drives score up but profile/activity pull it back
    assert 0.25 < result.composite < 0.80


def test_all_forks_scores_high(make_profile) -> None:  # type: ignore[no-untyped-def]
    profile = make_profile(total_repo_count=5, fork_repo_count=5, contribution_count=0)
    result = score_user(profile, SCAN_DATE)
    assert result.repo_pattern_score >= 0.75


def test_bot_username_pattern_increases_profile_score(make_profile) -> None:  # type: ignore[no-untyped-def]
    normal = make_profile(login="alice")
    bot = make_profile(login="user98765")
    s_normal = score_user(normal, SCAN_DATE)
    s_bot = score_user(bot, SCAN_DATE)
    assert s_bot.profile_score > s_normal.profile_score


@pytest.mark.parametrize(
    "login",
    ["user12345", "abc12345", "github-9999", "aaaaatest", "deadbeef12"],
)
def test_bot_patterns_detected(make_profile, login: str) -> None:  # type: ignore[no-untyped-def]
    profile = make_profile(login=login)
    result = score_user(profile, SCAN_DATE)
    assert result.profile_score > 0.0
