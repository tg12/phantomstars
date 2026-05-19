# phantomstars | JS Labs -- https://labs.jamessawyer.co.uk/
# AI Slop Intelligence -- https://labs.jamessawyer.co.uk/ai-slop-intelligence-dashboards/
# Apache-2.0 -- https://github.com/tg12/phantomstars
"""Immutable data models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

AnalysisMode = Literal["recent", "lifetime"]
Classification = Literal["likely_fake", "suspicious", "clean"]
EventKind = Literal["star", "fork"]


@dataclass(frozen=True, slots=True)
class UserProfile:
    """Profile fields fetched for a GitHub user account."""

    login: str
    node_id: str
    created_at: datetime
    followers: int
    following: int
    bio: str | None
    location: str | None
    company: str | None
    total_repo_count: int
    fork_repo_count: int

    @property
    def account_age_days(self) -> int:
        """Return age in whole days relative to current UTC time."""
        return (datetime.now(UTC) - self.created_at).days

    @property
    def all_repos_are_forks(self) -> bool:
        """Return True when every visible repo on the profile is a fork."""
        return self.total_repo_count > 0 and self.fork_repo_count == self.total_repo_count

    @property
    def fork_ratio(self) -> float:
        """Return the fork-to-total repository ratio."""
        if self.total_repo_count == 0:
            return 0.0
        return self.fork_repo_count / self.total_repo_count


@dataclass(frozen=True, slots=True)
class EngagementEvent:
    """A single star or fork event attributed to one login and repo."""

    user_login: str
    repo_full_name: str
    kind: EventKind
    occurred_at: datetime | None


@dataclass(frozen=True, slots=True)
class SuspicionScore:
    """Composite per-account scoring result for one scan date."""

    login: str
    account_age_score: float
    profile_score: float
    repo_pattern_score: float
    activity_score: float
    composite: float
    classification: Classification
    analysis_mode: AnalysisMode
    campaign_id: str | None
    scan_date: str
    account_created_at: str  # ISO date YYYY-MM-DD sourced from GitHub createdAt field
    target_repos: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RepoReport:
    """Per-repository summary derived from one completed scan."""

    full_name: str
    total_scanned: int
    likely_fake: int
    suspicious: int
    fakeness_ratio: float
    known_likely_fake: int
    known_likely_fake_ratio: float
    repeat_offenders: int
    classification: Classification
    campaign_count: int
    analysis_mode: AnalysisMode
    scan_date: str
