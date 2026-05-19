# phantomstars | JS Labs -- https://labs.jamessawyer.co.uk/
# AI Slop Intelligence -- https://labs.jamessawyer.co.uk/ai-slop-intelligence-dashboards/
# Apache-2.0 -- https://github.com/tg12/phantomstars
"""GitHub REST and GraphQL client with rate-limit awareness and tenacity retries."""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import requests
from bs4 import BeautifulSoup
from tenacity import (
    retry,
    retry_if_exception,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from phantomstars.config import (
    GITHUB_API_BASE,
    GITHUB_GRAPHQL_URL,
    GITHUB_TRENDING_URL,
    GRAPHQL_BATCH_SIZE,
    LIFETIME_GRAPHQL_BATCH_SIZE,
    LOOKBACK_HOURS,
    MAX_EVENTS_PER_REPO,
    MAX_LIFETIME_FORKS,
    MAX_LIFETIME_STARGAZERS,
    MAX_NEW_REPOS,
    MIN_STARS_NEW_REPO,
    RATE_LIMIT_PAUSE_THRESHOLD,
    REDDIT_BASE_URL,
    REDDIT_DISCOVERY_DAYS,
    REDDIT_POST_LIMIT,
    REDDIT_SEED_SUBREDDITS,
    REPO_DISCOVERY_DAYS,
)
from phantomstars.exceptions import LifetimeScanLimitError, RateLimitError, TrendingParseError
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

_LIFETIME_STARGAZER_QUERY = """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    stargazers(first: 100, after: $cursor) {
      pageInfo {
        hasNextPage
        endCursor
      }
      edges {
        starredAt
        node {
          login
        }
      }
    }
  }
}
"""

_LIFETIME_FORK_QUERY = """
query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    forks(first: 100, after: $cursor) {
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        createdAt
        owner {
          login
        }
      }
    }
  }
}
"""

_SCAN_EVENT_TYPES: frozenset[str] = frozenset({"WatchEvent", "ForkEvent"})
_GITHUB_REPO_URL_RE = re.compile(r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)")


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


def _should_retry_rest_error(exc: BaseException) -> bool:
    if isinstance(exc, requests.ConnectionError):
        return True
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return 500 <= exc.response.status_code < 600
    return False


class GitHubClient:
    """GitHub API client for discovery, profiling, and issue operations."""

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

    def get_reddit_seed_repos(self) -> dict[str, set[str]]:
        """Return repo seeds from recent Reddit posts keyed by discovery source."""
        cutoff = datetime.now(UTC) - timedelta(days=REDDIT_DISCOVERY_DAYS)
        repo_sources: dict[str, set[str]] = {}
        for subreddit in REDDIT_SEED_SUBREDDITS:
            source_label = f"reddit_{subreddit}"
            posts = self._fetch_reddit_new_posts(subreddit)
            for post in posts:
                created_utc = post.get("created_utc")
                if not isinstance(created_utc, (int, float)):
                    continue
                if datetime.fromtimestamp(created_utc, tz=UTC) < cutoff:
                    continue
                for repo in _extract_repos_from_reddit_post(post):
                    repo_sources.setdefault(repo, set()).add(source_label)
        return repo_sources

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

    def _fetch_reddit_new_posts(self, subreddit: str) -> list[dict[str, Any]]:
        """Return the most recent subreddit posts using Reddit's public JSON feed."""
        response = self._session.get(
            f"{REDDIT_BASE_URL}/r/{subreddit}/new/.json",
            params={"limit": REDDIT_POST_LIMIT},
            headers={"Accept": "application/json"},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        children = payload.get("data", {}).get("children", [])
        posts: list[dict[str, Any]] = []
        for child in children:
            if isinstance(child, dict):
                data = child.get("data")
                if isinstance(data, dict):
                    posts.append(data)
        return posts

    def get_lifetime_engagement(self, repo_full_name: str) -> list[EngagementEvent]:
        """Return lifetime star and fork engagement for a targeted repo."""
        repo = self._rest_get(f"{GITHUB_API_BASE}/repos/{repo_full_name}")
        stargazers_count = int(repo.get("stargazers_count", 0))
        forks_count = int(repo.get("forks_count", 0))
        if stargazers_count > MAX_LIFETIME_STARGAZERS or forks_count > MAX_LIFETIME_FORKS:
            raise LifetimeScanLimitError(
                f"Lifetime audit for {repo_full_name} exceeds limits: "
                f"{stargazers_count} stargazers, {forks_count} forks"
            )

        events: list[EngagementEvent] = []
        events.extend(self._get_lifetime_stargazer_events(repo_full_name))
        events.extend(self._get_lifetime_fork_events(repo_full_name))
        return events

    # ------------------------------------------------------------------
    # Bulk user profile fetch via GraphQL
    # ------------------------------------------------------------------

    def batch_fetch_profiles(
        self,
        logins: list[str],
        batch_size: int = GRAPHQL_BATCH_SIZE,
    ) -> dict[str, UserProfile]:
        """Fetch user profiles in GraphQL batches and return login-keyed results."""
        result: dict[str, UserProfile] = {}
        unique = list(dict.fromkeys(logins))  # deduplicate, preserve order

        for i in range(0, len(unique), batch_size):
            batch = unique[i : i + batch_size]
            data = self._graphql_user_batch(batch)
            for j, login in enumerate(batch):
                node = data.get(f"u{j}")
                if not node:
                    _log.warning("No GraphQL data for %s", login)
                    continue
                try:
                    result[login] = _parse_user_node(node)
                except (KeyError, ValueError) as exc:
                    _log.warning("Parse error for %s: %s", login, exc)
            if (i + len(batch)) % 1000 == 0:
                _log.info("Profile fetch progress: %d/%d", i + len(batch), len(unique))

        return result

    def batch_fetch_profiles_for_lifetime(self, logins: list[str]) -> dict[str, UserProfile]:
        """Fetch targeted-run profiles using the larger lifetime batch size."""
        return self.batch_fetch_profiles(logins, batch_size=LIFETIME_GRAPHQL_BATCH_SIZE)

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

    def _graphql_repository_connection(
        self,
        query: str,
        repo_full_name: str,
        connection_name: str,
    ) -> list[dict[str, Any]]:
        owner, name = repo_full_name.split("/", 1)
        cursor: str | None = None
        items: list[dict[str, Any]] = []
        page = 1

        while True:
            resp = self._graphql_post(
                {
                    "query": query,
                    "variables": {"owner": owner, "name": name, "cursor": cursor},
                }
            )
            repository = (resp.get("data") or {}).get("repository") or {}
            connection = repository.get(connection_name) or {}
            page_info = connection.get("pageInfo") or {}
            if connection_name == "stargazers":
                batch = connection.get("edges") or []
            else:
                batch = connection.get("nodes") or []
            if not isinstance(batch, list) or not batch:
                break
            items.extend(item for item in batch if isinstance(item, dict))
            if page % 50 == 0:
                _log.info(
                    "Lifetime %s fetch progress for %s: %d records",
                    connection_name,
                    repo_full_name,
                    len(items),
                )
            has_next = bool(page_info.get("hasNextPage"))
            cursor = page_info.get("endCursor")
            if not has_next or not isinstance(cursor, str) or not cursor:
                break
            page += 1

        return items

    @retry(
        retry=retry_if_exception_type(
            (requests.ConnectionError, requests.HTTPError, requests.ReadTimeout)
        ),
        wait=wait_exponential(multiplier=2, min=5, max=60),
        stop=stop_after_attempt(4),
    )
    def _graphql_post(self, payload: dict[str, Any]) -> dict[str, Any]:
        resp = self._session.post(GITHUB_GRAPHQL_URL, json=payload, timeout=60)
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
        retry=retry_if_exception(_should_retry_rest_error),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(4),
    )
    def _rest_get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        resp = self._session.get(url, params=params, headers=headers, timeout=20)
        self._check_rate_limit(resp)
        resp.raise_for_status()
        return resp.json()

    @retry(
        retry=retry_if_exception_type(requests.ConnectionError),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
    )
    def _rest_post(self, url: str, payload: dict[str, Any]) -> Any:
        resp = self._session.post(url, json=payload, timeout=20)
        self._check_rate_limit(resp)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Issue management
    # ------------------------------------------------------------------

    def ensure_labels(self, owner_repo: str, labels: list[dict[str, str]]) -> None:
        """Create labels on owner_repo if they do not already exist."""
        for label in labels:
            try:
                self._rest_post(f"{GITHUB_API_BASE}/repos/{owner_repo}/labels", label)
            except requests.HTTPError as exc:
                if exc.response is not None and exc.response.status_code == 422:
                    pass  # already exists
                else:
                    _log.warning("Could not create label '%s': %s", label.get("name"), exc)

    def find_open_issue(
        self,
        owner_repo: str,
        title_fragment: str,
        labels: str | None = "fake-engagement",
    ) -> int | None:
        """Return the issue number of an open fake-engagement issue whose title contains
        title_fragment, or None if no such issue exists."""
        for page in range(1, 5):
            params: dict[str, Any] = {
                "state": "open",
                "per_page": 100,
                "page": page,
            }
            if labels:
                params["labels"] = labels
            items = self._rest_get(
                f"{GITHUB_API_BASE}/repos/{owner_repo}/issues",
                params=params,
            )
            if not isinstance(items, list) or not items:
                break
            for item in items:
                if title_fragment in str(item.get("title", "")):
                    return int(item["number"])
        return None

    def create_issue(self, owner_repo: str, title: str, body: str, labels: list[str]) -> int:
        """Create an issue and return its number."""
        data = self._rest_post(
            f"{GITHUB_API_BASE}/repos/{owner_repo}/issues",
            {"title": title, "body": body, "labels": labels},
        )
        return int(data["number"])

    def add_comment(self, owner_repo: str, issue_number: int, body: str) -> None:
        """Append a comment to an existing issue."""
        self._rest_post(
            f"{GITHUB_API_BASE}/repos/{owner_repo}/issues/{issue_number}/comments",
            {"body": body},
        )

    def _check_rate_limit(self, resp: requests.Response) -> None:
        remaining = int(resp.headers.get("X-RateLimit-Remaining", 9999))
        reset_at = int(resp.headers.get("X-RateLimit-Reset", 0))
        if remaining < RATE_LIMIT_PAUSE_THRESHOLD:
            wait_s = max(0, reset_at - int(time.time())) + 5
            _log.warning("Rate limit low (%d remaining), sleeping %ds", remaining, wait_s)
            time.sleep(wait_s)
        if resp.status_code == 403 and remaining == 0:
            raise RateLimitError(reset_at)

    def _get_lifetime_stargazer_events(self, repo_full_name: str) -> list[EngagementEvent]:
        events: list[EngagementEvent] = []
        items = self._graphql_repository_connection(
            _LIFETIME_STARGAZER_QUERY,
            repo_full_name,
            "stargazers",
        )
        for item in items:
            starred_at = item.get("starredAt")
            user = item.get("node", {})
            login = str(user.get("login", "")).strip()
            if not login or not starred_at:
                continue
            events.append(
                EngagementEvent(
                    user_login=login,
                    repo_full_name=repo_full_name,
                    kind="star",
                    occurred_at=_parse_iso(str(starred_at)),
                )
            )
        return events

    def _get_lifetime_fork_events(self, repo_full_name: str) -> list[EngagementEvent]:
        events: list[EngagementEvent] = []
        items = self._graphql_repository_connection(
            _LIFETIME_FORK_QUERY,
            repo_full_name,
            "forks",
        )
        for item in items:
            owner = item.get("owner", {})
            login = str(owner.get("login", "")).strip()
            created_at = item.get("createdAt")
            if not login or not created_at:
                continue
            events.append(
                EngagementEvent(
                    user_login=login,
                    repo_full_name=repo_full_name,
                    kind="fork",
                    occurred_at=_parse_iso(str(created_at)),
                )
            )
        return events


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


def _extract_repos_from_reddit_post(post: dict[str, Any]) -> list[str]:
    """Extract unique owner/repo references from a Reddit post body or URL."""
    candidates: list[str] = []
    for key in ("selftext", "url", "url_overridden_by_dest"):
        value = post.get(key)
        if isinstance(value, str):
            candidates.append(value)

    repos: set[str] = set()
    for text in candidates:
        for match in _GITHUB_REPO_URL_RE.finditer(text):
            repo = match.group(1).rstrip("/").removesuffix(".git")
            if repo.count("/") != 1:
                continue
            repos.add(repo)
    return sorted(repos)
