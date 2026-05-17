"""Entry point. Reads GH_TOKEN from environment at the system boundary."""

from __future__ import annotations

import dataclasses
import logging
import os
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from phantomstars.campaigns import detect_campaigns
from phantomstars.config import REPOS_FILE, SUSPECTS_FILE
from phantomstars.exceptions import TrendingParseError
from phantomstars.github_client import GitHubClient
from phantomstars.heuristics import score_user
from phantomstars.logging_config import setup_logging
from phantomstars.models import Classification, EngagementEvent, RepoReport, SuspicionScore
from phantomstars.reporter import update_readme
from phantomstars.storage import append_reports, append_suspects, load_allowlist

_log = logging.getLogger(__name__)


def _classify_repo(fakeness_ratio: float) -> Classification:
    if fakeness_ratio >= 0.40:
        return "likely_fake"
    if fakeness_ratio >= 0.20:
        return "suspicious"
    return "clean"


def _build_repo_reports(
    final_scores: list[SuspicionScore],
    flat_events: list[EngagementEvent],
    scan_date: str,
) -> list[RepoReport]:
    repo_all_users: dict[str, set[str]] = defaultdict(set)
    for ev in flat_events:
        repo_all_users[ev.repo_full_name].add(ev.user_login)

    repo_likely: dict[str, int] = defaultdict(int)
    repo_suspicious: dict[str, int] = defaultdict(int)
    repo_campaigns: dict[str, set[str]] = defaultdict(set)

    for score in final_scores:
        if score.classification == "clean":
            continue
        for repo in score.target_repos:
            if score.classification == "likely_fake":
                repo_likely[repo] += 1
            else:
                repo_suspicious[repo] += 1
            if score.campaign_id:
                repo_campaigns[repo].add(score.campaign_id)

    reports: list[RepoReport] = []
    targeted = set(repo_likely) | set(repo_suspicious)
    for repo in targeted:
        total_engagers = len(repo_all_users.get(repo, set()))
        likely = repo_likely[repo]
        suspicious = repo_suspicious[repo]
        fakeness_ratio = round(likely / total_engagers, 3) if total_engagers else 0.0
        reports.append(
            RepoReport(
                full_name=repo,
                total_scanned=total_engagers,
                likely_fake=likely,
                suspicious=suspicious,
                fakeness_ratio=fakeness_ratio,
                classification=_classify_repo(fakeness_ratio),
                campaign_count=len(repo_campaigns[repo]),
                scan_date=scan_date,
            )
        )

    return sorted(reports, key=lambda r: r.likely_fake, reverse=True)


def _write_step_summary(
    suspects: list[SuspicionScore],
    repo_reports: list[RepoReport],
    campaign_map: dict[str, str],
    scan_date: str,
) -> None:
    """Write a formatted markdown report to $GITHUB_STEP_SUMMARY if running in Actions."""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    likely_count = sum(1 for s in suspects if s.classification == "likely_fake")
    suspicious_count = sum(1 for s in suspects if s.classification == "suspicious")
    campaign_count = len(set(campaign_map.values()))
    high_risk_repos = [r for r in repo_reports if r.classification == "likely_fake"]

    lines = [
        f"## Phantom Stars Scan — {scan_date}",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Likely fake accounts | **{likely_count}** |",
        f"| Suspicious accounts | {suspicious_count} |",
        f"| Campaigns detected | **{campaign_count}** |",
        f"| Repos targeted | {len(repo_reports)} |",
        f"| High-risk repos (fakeness ≥ 40%) | **{len(high_risk_repos)}** |",
        "",
    ]

    if repo_reports:
        lines += [
            "### Most-targeted repos",
            "",
            "| Repo | Engagers | Likely Fake | Fakeness % | Campaigns |",
            "|------|----------|-------------|------------|-----------|",
        ]
        for r in repo_reports[:15]:
            pct = f"{r.fakeness_ratio * 100:.1f}%"
            flag = " :warning:" if r.classification == "likely_fake" else ""
            lines.append(
                f"| [{r.full_name}](https://github.com/{r.full_name}){flag}"
                f" | {r.total_scanned} | {r.likely_fake} | {pct} | {r.campaign_count} |"
            )
        lines.append("")

    if campaign_count > 0:
        campaign_sizes: dict[str, int] = defaultdict(int)
        for s in suspects:
            if s.campaign_id:
                campaign_sizes[s.campaign_id] += 1

        lines += [
            "### Active campaigns",
            "",
            "| Campaign ID | Members | Classification |",
            "|-------------|---------|----------------|",
        ]
        for cid, size in sorted(campaign_sizes.items(), key=lambda x: x[1], reverse=True)[:10]:
            lines.append(f"| `{cid}` | {size} | likely_fake |")
        lines.append("")

    lines += [
        "---",
        "*phantomstars performs read-only analysis of public GitHub data.*"
        " *All findings are probabilistic. This tool does not interact with"
        " or notify any external repository.*",
    ]

    Path(summary_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    _log.info("GitHub Actions step summary written (%d lines)", len(lines))


def main() -> None:
    setup_logging()
    gh_token: str = os.environ["GH_TOKEN"]
    scan_date = datetime.now(UTC).date().isoformat()
    suspects_path = Path(SUSPECTS_FILE)
    repos_path = Path(REPOS_FILE)
    client = GitHubClient(token=gh_token)

    # 1. Collect repos to scan from both sources
    repo_set: set[str] = set()

    try:
        trending = client.get_trending_repos()
        repo_set.update(trending)
        _log.info("Trending: %d repos", len(trending))
    except TrendingParseError as exc:
        _log.error("Trending scrape failed: %s -- falling back to search only", exc)

    new_repos = client.get_new_repos()
    repo_set.update(new_repos)
    _log.info("New repos (recent): %d repos", len(new_repos))
    _log.info("Total repos to scan: %d", len(repo_set))

    # 2. Collect engagement events across all repos
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
    scores: dict[str, SuspicionScore] = {
        login: score_user(profile, scan_date) for login, profile in profiles.items()
    }

    # 5. Detect campaigns
    campaign_map = detect_campaigns(flat_events, scores)
    _log.info(
        "Campaign members: %d across %d campaigns",
        len(campaign_map),
        len(set(campaign_map.values())),
    )

    # 6. Build login -> repos mapping from events
    login_repos: dict[str, list[str]] = defaultdict(list)
    for ev in flat_events:
        if ev.repo_full_name not in login_repos[ev.user_login]:
            login_repos[ev.user_login].append(ev.repo_full_name)

    # 7. Rebuild scores with campaign IDs and target_repos (SuspicionScore is frozen)
    final_scores: list[SuspicionScore] = [
        dataclasses.replace(
            score,
            campaign_id=campaign_map.get(login),
            target_repos=tuple(sorted(login_repos.get(login, []))),
        )
        for login, score in scores.items()
    ]

    # 8. Persist suspects only -- skip allowlisted accounts
    allowlist = load_allowlist()
    if allowlist:
        _log.info("Allowlist contains %d entries", len(allowlist))
    suspects = [
        s for s in final_scores if s.classification != "clean" and s.login.lower() not in allowlist
    ]
    _log.info(
        "Suspects: %d likely_fake, %d suspicious",
        sum(1 for s in suspects if s.classification == "likely_fake"),
        sum(1 for s in suspects if s.classification == "suspicious"),
    )
    append_suspects(suspects, suspects_path)

    # 9. Produce per-repo intelligence
    repo_reports = _build_repo_reports(final_scores, flat_events, scan_date)
    _log.info(
        "Repo reports: %d targeted repos (%d likely_fake classification)",
        len(repo_reports),
        sum(1 for r in repo_reports if r.classification == "likely_fake"),
    )
    append_reports(repo_reports, repos_path)

    # 10. Update README dashboard
    update_readme(suspects_path, repos_path)

    # 11. Write GitHub Actions step summary
    _write_step_summary(suspects, repo_reports, campaign_map, scan_date)

    _log.info("Scan complete for %s", scan_date)


if __name__ == "__main__":
    main()
