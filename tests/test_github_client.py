"""Tests for GitHub client behavior."""

from __future__ import annotations

import logging

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
