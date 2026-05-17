"""Entry point. Reads GH_TOKEN from environment at the system boundary."""
from __future__ import annotations

import dataclasses
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from phantomstars.campaigns import detect_campaigns
from phantomstars.config import SUSPECTS_FILE
from phantomstars.exceptions import TrendingParseError
from phantomstars.github_client import GitHubClient
from phantomstars.heuristics import score_user
from phantomstars.logging_config import setup_logging
from phantomstars.models import SuspicionScore
from phantomstars.reporter import update_readme
from phantomstars.storage import append_suspects

_log = logging.getLogger(__name__)

GH_TOKEN: str = os.environ["GH_TOKEN"]


def main() -> None:
    setup_logging()
    scan_date = datetime.now(timezone.utc).date().isoformat()
    suspects_path = Path(SUSPECTS_FILE)
    client = GitHubClient(token=GH_TOKEN)

    # 1. Collect repos to scan from both sources
    repo_set: set[str] = set()

    try:
        trending = client.get_trending_repos()
        repo_set.update(trending)
        _log.info("Trending: %d repos", len(trending))
    except TrendingParseError as exc:
        _log.error("Trending scrape failed: %s — falling back to search only", exc)

    new_repos = client.get_new_repos()
    repo_set.update(new_repos)
    _log.info("New repos (24h): %d repos", len(new_repos))
    _log.info("Total repos to scan: %d", len(repo_set))

    # 2. Collect engagement events across all repos
    from phantomstars.models import EngagementEvent
    flat_events: list[EngagementEvent] = []
    for repo in sorted(repo_set):
        _log.info("Scanning events: %s", repo)
        flat_events.extend(client.get_recent_engagement(repo))
    _log.info("Total engagement events: %d", len(flat_events))

    # 3. Fetch user profiles for unique logins
    logins = list({ev.user_login for ev in flat_events})
    _log.info("Unique users to profile: %d", len(logins))
    profiles = client.batch_fetch_profiles(logins)
    _log.info("Profiles fetched: %d", len(profiles))

    # 4. Score every user
    scores: dict[str, SuspicionScore] = {}
    for login, profile in profiles.items():
        scores[login] = score_user(profile, scan_date)

    # 5. Detect campaigns
    campaign_map = detect_campaigns(flat_events, scores)
    _log.info("Campaign members: %d across %d campaigns", len(campaign_map), len(set(campaign_map.values())))

    # 6. Rebuild scores with campaign IDs (SuspicionScore is frozen, create new)
    final_scores: list[SuspicionScore] = []
    for login, score in scores.items():
        if login in campaign_map:
            record = dataclasses.replace(score, campaign_id=campaign_map[login])
        else:
            record = score
        final_scores.append(record)

    # 7. Persist suspects only (clean accounts are not stored)
    suspects = [s for s in final_scores if s.classification != "clean"]
    _log.info(
        "Suspects: %d likely_fake, %d suspicious",
        sum(1 for s in suspects if s.classification == "likely_fake"),
        sum(1 for s in suspects if s.classification == "suspicious"),
    )
    append_suspects(suspects, suspects_path)

    # 8. Update README dashboard
    update_readme(suspects_path)
    _log.info("Scan complete for %s", scan_date)


if __name__ == "__main__":
    main()
