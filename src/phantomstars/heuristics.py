# phantomstars | JS Labs -- https://labs.jamessawyer.co.uk/
# AI Slop Intelligence -- https://labs.jamessawyer.co.uk/ai-slop-intelligence-dashboards/
# Apache-2.0 -- https://github.com/tg12/phantomstars
"""Scoring engine. Each sub-scorer returns 0.0 (clean) to 1.0 (likely fake)."""

from __future__ import annotations

import re

from phantomstars.config import (
    ACTIVITY_MIN_AGE_DAYS,
    AGE_BAND_HIGH,
    AGE_BAND_LOW,
    AGE_BAND_MED,
    SCORE_LIKELY_FAKE,
    SCORE_SUSPICIOUS,
    WEIGHT_ACCOUNT_AGE,
    WEIGHT_ACTIVITY,
    WEIGHT_PROFILE,
    WEIGHT_REPO_PATTERN,
)
from phantomstars.models import Classification, SuspicionScore, UserProfile

_BOT_USERNAME_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^[a-z]+-[a-z]+-\d{4,}$"),
    re.compile(r"^[a-z]+\d{4,}$"),
    re.compile(r"^[a-f0-9]{8,}$"),
    re.compile(r"^user\d+$", re.IGNORECASE),
    re.compile(r"^github[_-]?\d+$", re.IGNORECASE),
    re.compile(r"(.)\1{3,}"),
]


def _score_account_age(age_days: int) -> float:
    if age_days < 2:
        return 1.00
    if age_days < AGE_BAND_HIGH:
        return 0.90
    if age_days < AGE_BAND_MED:
        return 0.55
    if age_days < AGE_BAND_LOW:
        return 0.20
    return 0.00


def _score_profile(profile: UserProfile) -> float:
    score = 0.0
    if not profile.bio:
        score += 0.25
    if not profile.location:
        score += 0.15
    if not profile.company:
        score += 0.10
    if profile.followers == 0:
        score += 0.30
    if profile.following == 0:
        score += 0.10
    for pat in _BOT_USERNAME_PATTERNS:
        if pat.search(profile.login.lower()):
            score += 0.20
            break
    return min(score, 1.0)


def _score_activity(profile: UserProfile) -> float:
    """Detect ghost accounts: old enough to have built activity but have none.

    Uses only fields already in the GraphQL fragment (no extra API calls).
    Returns 0.0 for accounts younger than ACTIVITY_MIN_AGE_DAYS — too new to judge.
    """
    if profile.account_age_days < ACTIVITY_MIN_AGE_DAYS:
        return 0.0
    # Fully dormant: old account, zero repos, zero social graph
    if profile.total_repo_count == 0 and profile.followers == 0 and profile.following == 0:
        return 0.80
    # Old account with no repos at all
    if profile.total_repo_count == 0:
        return 0.60
    # Only forked repos + no social graph = sitting sleeper bot
    if profile.all_repos_are_forks and profile.followers == 0 and profile.following == 0:
        return 0.50
    return 0.0


def _score_repo_pattern(profile: UserProfile) -> float:
    if profile.total_repo_count == 0:
        return 0.90
    if profile.all_repos_are_forks:
        return 0.80
    if profile.fork_ratio > 0.85:
        return 0.55
    return 0.00


def _classify(composite: float) -> Classification:
    if composite >= SCORE_LIKELY_FAKE:
        return "likely_fake"
    if composite >= SCORE_SUSPICIOUS:
        return "suspicious"
    return "clean"


def score_user(profile: UserProfile, scan_date: str) -> SuspicionScore:
    age_s = _score_account_age(profile.account_age_days)
    prof_s = _score_profile(profile)
    repo_s = _score_repo_pattern(profile)
    act_s = _score_activity(profile)
    composite = (
        age_s * WEIGHT_ACCOUNT_AGE
        + prof_s * WEIGHT_PROFILE
        + repo_s * WEIGHT_REPO_PATTERN
        + act_s * WEIGHT_ACTIVITY
    )
    return SuspicionScore(
        login=profile.login,
        account_age_score=round(age_s, 3),
        profile_score=round(prof_s, 3),
        repo_pattern_score=round(repo_s, 3),
        activity_score=round(act_s, 3),
        composite=round(composite, 3),
        classification=_classify(composite),
        campaign_id=None,
        scan_date=scan_date,
        account_created_at=profile.created_at.date().isoformat(),
    )
