"""GitHub REST and GraphQL client with rate-limit awareness and tenacity retries."""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import requests
from bs4 import BeautifulSoup
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from phantomstars.config import (
    GITHUB_API_BASE,
    GITHUB_GRAPHQL_URL,
    GITHUB_TRENDING_URL,
    GRAPHQL_BATCH_SIZE,
    LOOKBACK_HOURS,
    MAX_EVENTS_PER_REPO,
    MAX_NEW_REPOS,
    MIN_STARS_NEW_REPO,
    RATE_LIMIT_PAUSE_THRESHOLD,
    REPO_DISCOVERY_DAYS,
)
from phantomstars.exceptions import RateLimitError, TrendingParseError
from phantomstars.models import EngagementEvent, EventKind, UserProfile

_log = logging.getLogger(__name__)

_GRAPHQL_FRAGMENT = """
fragment F on User {
  login
  id
  createdAt
  followers { totalCount }
  following { totalCount }
  bio
  location
  company
  allRepos: repositories(first: 1) { totalCount }
  forkRepos: repositories(isFork: true, first: 1) { totalCount }
}
"""

_SCAN_EVENT_TYPES: frozenset[str] = frozenset({"WatchEvent", "ForkEvent"})


def _parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _parse_user_node(node: dict[str, Any]) -> UserProfile:
    return UserProfile(
        login=node["login"],
        node_id=node["id"],
        created_at=_parse_iso(node["createdAt"]),
        followers=node["followers"]["totalCount"],
        following=node["following"]["totalCount"],
        bio=node.get("bio") or None,
        location=node.get("location") or None,
        company=node.get("company") or None,
        total_repo_count=node["allRepos"]["totalCount"],
        fork_repo_count=node["forkRepos"]["totalCount"],
    )


class GitHubClient:
    def __init__(self, token: str) -> None:
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "phantomstars/0.1 (github.com/phantomstars)",
            }
        )

    # ------------------------------------------------------------------
    # Trending scrape
    # ------------------------------------------------------------------

    def get_trending_repos(self) -> list[str]:
        """Return list of 'owner/repo' strings from today's trending page."""
        resp = self._session.get(GITHUB_TRENDING_URL, timeout=20)
        resp.raise_for_status()
        return _parse_trending_html(resp.text)

    # ------------------------------------------------------------------
    # New repos via search
    # ------------------------------------------------------------------

    def get_new_repos(self) -> list[str]:
        """Return repos created in the last REPO_DISCOVERY_DAYS with >= MIN_STARS_NEW_REPO stars.

        Uses a longer window than the events scan so multi-day campaigns on newer repos
        are caught even when the bulk of their fake engagement predates today's 24h window.
        """
        cutoff = datetime.now(UTC) - timedelta(days=REPO_DISCOVERY_DAYS)
        date_str = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
        query = f"created:>{date_str} stars:>={MIN_STARS_NEW_REPO}"
        repos: list[str] = []
        page = 1

        while len(repos) < MAX_NEW_REPOS:
            data = self._rest_get(
                f"{GITHUB_API_BASE}/search/repositories",
                params={
                    "q": query,
                    "sort": "stars",
                    "order": "desc",
                    "per_page": 100,
                    "page": page,
                },
            )
            items = data.get("items", [])
            if not items:
                break
            for item in items:
                full_name = item.get("full_name", "")
                if full_name:
                    repos.append(full_name)
            page += 1

        return repos[:MAX_NEW_REPOS]

    # ------------------------------------------------------------------
    # Engagement events
    # ------------------------------------------------------------------

    def get_recent_engagement(self, repo_full_name: str) -> list[EngagementEvent]:
        """Return star and fork events from the last LOOKBACK_HOURS via Events API."""
        cutoff = datetime.now(UTC) - timedelta(hours=LOOKBACK_HOURS)
        events: list[EngagementEvent] = []
        url = f"{GITHUB_API_BASE}/repos/{repo_full_name}/events"

        for page in range(1, 4):  # max 300 events
            try:
                items = self._rest_get(url, params={"per_page": 100, "page": page})
            except requests.HTTPError as exc:
                if exc.response is not None and exc.response.status_code in (404, 451):
                    _log.warning("Repo unavailable: %s (%s)", repo_full_name, exc)
                    return events
                raise

            if not isinstance(items, list) or not items:
                break

            reached_cutoff = False
            for item in items:
                kind = item.get("type", "")
                if kind not in _SCAN_EVENT_TYPES:
                    continue

                occurred_at: datetime | None = None
                raw_ts = item.get("created_at")
                if raw_ts:
                    occurred_at = _parse_iso(raw_ts)
                    if occurred_at < cutoff:
                        reached_cutoff = True
                        break

                if kind == "WatchEvent" and item.get("payload", {}).get("action") != "started":
                    continue

                actor = item.get("actor", {})
                login = actor.get("login", "")
                if not login:
                    continue

                event_kind: EventKind = "star" if kind == "WatchEvent" else "fork"
                events.append(
                    EngagementEvent(
                        user_login=login,
                        repo_full_name=repo_full_name,
                        kind=event_kind,
                        occurred_at=occurred_at,
                    )
                )

            if reached_cutoff or len(events) >= MAX_EVENTS_PER_REPO:
                break

        return events

    # ------------------------------------------------------------------
    # Bulk user profile fetch via GraphQL
    # ------------------------------------------------------------------

    def batch_fetch_profiles(self, logins: list[str]) -> dict[str, UserProfile]:
        result: dict[str, UserProfile] = {}
        unique = list(dict.fromkeys(logins))  # deduplicate, preserve order

        for i in range(0, len(unique), GRAPHQL_BATCH_SIZE):
            batch = unique[i : i + GRAPHQL_BATCH_SIZE]
            data = self._graphql_user_batch(batch)
            for j, login in enumerate(batch):
                node = data.get(f"u{j}")
                if not node:
                    _log.debug("No GraphQL data for %s", login)
                    continue
                try:
                    result[login] = _parse_user_node(node)
                except (KeyError, ValueError) as exc:
                    _log.warning("Parse error for %s: %s", login, exc)

        return result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _graphql_user_batch(self, logins: list[str]) -> dict[str, Any]:
        aliases = "\n".join(
            f"  u{i}: user(login: {json.dumps(login)}) {{ ...F }}" for i, login in enumerate(logins)
        )
        query = f"{_GRAPHQL_FRAGMENT}\nquery {{\n{aliases}\n}}"
        resp = self._graphql_post({"query": query})
        result: dict[str, Any] = resp.get("data") or {}
        return result

    @retry(
        retry=retry_if_exception_type((requests.ConnectionError, requests.HTTPError)),
        wait=wait_exponential(multiplier=2, min=5, max=60),
        stop=stop_after_attempt(4),
    )
    def _graphql_post(self, payload: dict[str, Any]) -> dict[str, Any]:
        resp = self._session.post(GITHUB_GRAPHQL_URL, json=payload, timeout=30)
        self._check_rate_limit(resp)
        if resp.status_code == 403:
            _log.warning("GraphQL 403 — backing off before retry")
            resp.raise_for_status()
        raw = resp.json()
        data: dict[str, Any] = raw if isinstance(raw, dict) else {}
        if "errors" in data:
            _log.warning("GraphQL partial errors: %d error(s)", len(data["errors"]))
        return data

    @retry(
        retry=retry_if_exception_type(requests.ConnectionError),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(4),
    )
    def _rest_get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        resp = self._session.get(url, params=params, timeout=20)
        self._check_rate_limit(resp)
        resp.raise_for_status()
        return resp.json()

    def _check_rate_limit(self, resp: requests.Response) -> None:
        remaining = int(resp.headers.get("X-RateLimit-Remaining", 9999))
        reset_at = int(resp.headers.get("X-RateLimit-Reset", 0))
        if remaining < RATE_LIMIT_PAUSE_THRESHOLD:
            wait_s = max(0, reset_at - int(time.time())) + 5
            _log.warning("Rate limit low (%d remaining), sleeping %ds", remaining, wait_s)
            time.sleep(wait_s)
        if resp.status_code == 403 and remaining == 0:
            raise RateLimitError(reset_at)


def _parse_trending_html(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    repos: list[str] = []
    for article in soup.select("article.Box-row"):
        link = article.select_one("h2 a")
        if not link:
            continue
        href = link.get("href", "")
        if isinstance(href, str) and href.count("/") == 2:
            repos.append(href.lstrip("/"))
    if not repos:
        raise TrendingParseError(
            "No repos found in trending HTML — page structure may have changed"
        )
    _log.info("Parsed %d trending repos", len(repos))
    return repos
