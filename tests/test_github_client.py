"""Tests for GitHub client behavior."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import requests
from phantomstars.github_client import GitHubClient, _extract_repos_from_reddit_post


def test_batch_fetch_profiles_warns_when_graphql_node_missing(caplog) -> None:
    client = GitHubClient(token="test-token")

    def fake_batch(logins: list[str]) -> dict[str, object]:
        assert logins == ["missing-user"]
        return {}

    client._graphql_user_batch = fake_batch  # type: ignore[method-assign]

    with caplog.at_level(logging.WARNING):
        profiles = client.batch_fetch_profiles(["missing-user"])

    assert profiles == {}
    assert "No GraphQL data for missing-user" in caplog.text


def test_extract_repos_from_reddit_post_deduplicates_owner_repo_links() -> None:
    repos = _extract_repos_from_reddit_post(
        {
            "selftext": (
                "https://github.com/example/project\n"
                "mirror https://github.com/example/project.git\n"
            ),
            "url": "https://github.com/other/repo",
        }
    )

    assert repos == ["example/project", "other/repo"]


def test_fetch_reddit_new_posts_skips_blocked_subreddit(caplog) -> None:
    client = GitHubClient(token="test-token")
    response = MagicMock()
    response.status_code = 403
    response.raise_for_status.side_effect = requests.HTTPError(response=response)
    client._session.get = MagicMock(return_value=response)  # type: ignore[method-assign]

    with caplog.at_level(logging.WARNING):
        posts = client._fetch_reddit_new_posts("osinttools")

    assert posts == []
    assert "Skipping Reddit seed source r/osinttools due to HTTP 403" in caplog.text
