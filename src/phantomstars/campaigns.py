"""Campaign detection via timestamp-clustering and union-find. No external dependencies."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from phantomstars.config import CAMPAIGN_WINDOW_HOURS, MIN_CAMPAIGN_SIZE, SCORE_SUSPICIOUS
from phantomstars.models import EngagementEvent, SuspicionScore


@dataclass(frozen=True, slots=True)
class _TimedEvent:
    user_login: str
    occurred_at: datetime


class _UnionFind:
    def __init__(self) -> None:
        self._parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        if x not in self._parent:
            self._parent[x] = x
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]  # path compression
            x = self._parent[x]
        return x

    def union(self, x: str, y: str) -> None:
        rx, ry = self.find(x), self.find(y)
        if rx != ry:
            self._parent[rx] = ry


def detect_campaigns(
    events: list[EngagementEvent],
    scores: dict[str, SuspicionScore],
) -> dict[str, str]:
    """Return mapping of login -> campaign_id for accounts that form a campaign.

    A campaign is a connected component of >= MIN_CAMPAIGN_SIZE suspicious
    accounts that engaged with the same repo within CAMPAIGN_WINDOW_HOURS.
    """
    suspects: set[str] = {login for login, s in scores.items() if s.composite >= SCORE_SUSPICIOUS}

    # Bucket events by repo, narrowing occurred_at to non-None
    repo_events: dict[str, list[_TimedEvent]] = defaultdict(list)
    for ev in events:
        if ev.user_login in suspects and ev.occurred_at is not None:
            repo_events[ev.repo_full_name].append(
                _TimedEvent(user_login=ev.user_login, occurred_at=ev.occurred_at)
            )

    uf = _UnionFind()
    window = timedelta(hours=CAMPAIGN_WINDOW_HOURS)

    for repo_evs in repo_events.values():
        sorted_evs = sorted(repo_evs, key=lambda e: e.occurred_at)
        for i, ev_i in enumerate(sorted_evs):
            for ev_j in sorted_evs[i + 1 :]:
                if ev_j.occurred_at - ev_i.occurred_at > window:
                    break
                uf.union(ev_i.user_login, ev_j.user_login)

    # Find connected components among suspects only
    components: dict[str, list[str]] = defaultdict(list)
    for login in suspects:
        root = uf.find(login)
        components[root].append(login)

    campaign_map: dict[str, str] = {}
    for _root, members in components.items():
        if len(members) >= MIN_CAMPAIGN_SIZE:
            # Deterministic ID: hash of sorted member set so the same group of accounts
            # produces the same campaign ID across independent scan runs.
            member_key = "|".join(sorted(members))
            digest = hashlib.sha256(member_key.encode()).hexdigest()[:8]
            campaign_id = f"c-{digest}"
            for m in members:
                campaign_map[m] = campaign_id

    return campaign_map
