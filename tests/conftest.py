"""Shared test fixtures."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from phantomstars.models import UserProfile


def _make_profile(
    login: str = "testuser",
    age_days: int = 365,
    followers: int = 50,
    following: int = 40,
    bio: str | None = "A developer",
    location: str | None = "UK",
    company: str | None = None,
    contribution_count: int = 200,
    total_repo_count: int = 10,
    fork_repo_count: int = 2,
) -> UserProfile:
    from datetime import timedelta

    created_at = datetime.now(timezone.utc) - timedelta(days=age_days)
    return UserProfile(
        login=login,
        node_id="MDQ6VXNlcjE=",
        created_at=created_at,
        followers=followers,
        following=following,
        bio=bio,
        location=location,
        company=company,
        contribution_count=contribution_count,
        total_repo_count=total_repo_count,
        fork_repo_count=fork_repo_count,
    )


@pytest.fixture()
def clean_profile() -> UserProfile:
    return _make_profile()


@pytest.fixture()
def bot_profile() -> UserProfile:
    return _make_profile(
        login="user12345",
        age_days=2,
        followers=0,
        following=0,
        bio=None,
        location=None,
        company=None,
        contribution_count=0,
        total_repo_count=1,
        fork_repo_count=1,
    )


@pytest.fixture()
def make_profile():  # type: ignore[no-untyped-def]
    return _make_profile
