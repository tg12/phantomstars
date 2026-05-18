"""Tests for the scoring engine."""

from __future__ import annotations

import pytest

from phantomstars.config import RECENT_ANALYSIS_MODE
from phantomstars.heuristics import _score_activity, score_user
from phantomstars.models import UserProfile

SCAN_DATE = "2026-05-17"


def test_clean_profile_scores_low(clean_profile: UserProfile) -> None:
    result = score_user(clean_profile, SCAN_DATE, RECENT_ANALYSIS_MODE)
    assert result.classification == "clean"
    assert result.composite < 0.45


def test_bot_profile_scores_likely_fake(bot_profile: UserProfile) -> None:
    result = score_user(bot_profile, SCAN_DATE, RECENT_ANALYSIS_MODE)
    assert result.classification == "likely_fake"
    assert result.composite >= 0.75


def test_scan_date_preserved(clean_profile: UserProfile) -> None:
    result = score_user(clean_profile, SCAN_DATE, RECENT_ANALYSIS_MODE)
    assert result.scan_date == SCAN_DATE


def test_campaign_id_is_none_by_default(bot_profile: UserProfile) -> None:
    result = score_user(bot_profile, SCAN_DATE, RECENT_ANALYSIS_MODE)
    assert result.campaign_id is None


def test_target_repos_empty_by_default(bot_profile: UserProfile) -> None:
    result = score_user(bot_profile, SCAN_DATE, RECENT_ANALYSIS_MODE)
    assert result.target_repos == ()


def test_analysis_mode_preserved(clean_profile: UserProfile) -> None:
    result = score_user(clean_profile, SCAN_DATE, RECENT_ANALYSIS_MODE)
    assert result.analysis_mode == RECENT_ANALYSIS_MODE


def test_composite_is_weighted_sum(make_profile) -> None:  # type: ignore[no-untyped-def]
    profile = make_profile(
        login="newdev",
        age_days=1,
        followers=100,
        following=80,
        bio="Engineer",
        location="Berlin",
        company="ACME",
        total_repo_count=5,
        fork_repo_count=1,
    )
    result = score_user(profile, SCAN_DATE, RECENT_ANALYSIS_MODE)
    # New account drives age score high, but solid profile pulls composite down
    assert 0.25 < result.composite < 0.80


def test_all_forks_scores_high(make_profile) -> None:  # type: ignore[no-untyped-def]
    profile = make_profile(total_repo_count=5, fork_repo_count=5)
    result = score_user(profile, SCAN_DATE, RECENT_ANALYSIS_MODE)
    assert result.repo_pattern_score >= 0.75


def test_bot_username_pattern_increases_profile_score(make_profile) -> None:  # type: ignore[no-untyped-def]
    normal = make_profile(login="alice")
    bot = make_profile(login="user98765")
    s_normal = score_user(normal, SCAN_DATE, RECENT_ANALYSIS_MODE)
    s_bot = score_user(bot, SCAN_DATE, RECENT_ANALYSIS_MODE)
    assert s_bot.profile_score > s_normal.profile_score


@pytest.mark.parametrize(
    "login",
    ["user12345", "abc12345", "github-9999", "aaaaatest", "deadbeef12"],
)
def test_bot_patterns_detected(make_profile, login: str) -> None:  # type: ignore[no-untyped-def]
    profile = make_profile(login=login)
    result = score_user(profile, SCAN_DATE, RECENT_ANALYSIS_MODE)
    assert result.profile_score > 0.0


# --- activity_score tests ---


def test_activity_score_zero_for_new_accounts(make_profile) -> None:  # type: ignore[no-untyped-def]
    # Accounts < 14 days old never get penalised for inactivity
    profile = make_profile(age_days=10, total_repo_count=0, followers=0, following=0)
    from phantomstars.heuristics import _score_activity

    assert _score_activity(profile) == 0.0


def test_activity_score_high_for_ghost_account(make_profile) -> None:  # type: ignore[no-untyped-def]
    # Old account, nothing: no repos, no followers, no following
    profile = make_profile(
        age_days=120, total_repo_count=0, followers=0, following=0, bio=None, location=None
    )
    assert _score_activity(profile) == 0.80


def test_activity_score_moderate_for_old_no_repos(make_profile) -> None:  # type: ignore[no-untyped-def]
    # Old account with social graph but no repos
    profile = make_profile(age_days=60, total_repo_count=0, followers=5, following=10)
    assert _score_activity(profile) == 0.60


def test_activity_score_moderate_for_all_forks_no_social(make_profile) -> None:  # type: ignore[no-untyped-def]
    profile = make_profile(
        age_days=45, total_repo_count=3, fork_repo_count=3, followers=0, following=0
    )
    assert _score_activity(profile) == 0.50


def test_activity_score_zero_for_active_account(make_profile) -> None:  # type: ignore[no-untyped-def]
    profile = make_profile(age_days=200, total_repo_count=8, fork_repo_count=2, followers=20)
    assert _score_activity(profile) == 0.0


def test_ghost_account_pushes_score_above_threshold(make_profile) -> None:  # type: ignore[no-untyped-def]
    # An account that's old, empty, but otherwise moderate profile should get flagged
    profile = make_profile(
        login="dormant-account",
        age_days=180,
        total_repo_count=0,
        fork_repo_count=0,
        followers=0,
        following=0,
        bio=None,
        location=None,
        company=None,
    )
    result = score_user(profile, SCAN_DATE, RECENT_ANALYSIS_MODE)
    # activity=0.80, profile=0.80 (no bio/loc/followers/following), age=0.0, repo=0.90
    # composite = 0.0*0.35 + 0.80*0.30 + 0.90*0.25 + 0.80*0.10 = 0.0 + 0.24 + 0.225 + 0.08 = 0.545
    assert result.classification == "suspicious"
    assert result.activity_score == 0.80
