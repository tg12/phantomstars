"""Tests for GitHub client behavior."""

from __future__ import annotations

import logging

from phantomstars.github_client import GitHubClient


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
