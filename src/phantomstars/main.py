# phantomstars | JS Labs -- https://labs.jamessawyer.co.uk/
# AI Slop Intelligence -- https://labs.jamessawyer.co.uk/ai-slop-intelligence-dashboards/
# Apache-2.0 -- https://github.com/tg12/phantomstars
"""Entry point. Reads GH_TOKEN from environment at the system boundary."""

from __future__ import annotations

import dataclasses
import logging
import os
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from phantomstars.campaigns import detect_campaigns
from phantomstars.config import (
    LIFETIME_ANALYSIS_MODE,
    RECENT_ANALYSIS_MODE,
    REPOS_FILE,
    SUSPECTS_FILE,
)
from phantomstars.exceptions import TrendingParseError
from phantomstars.github_client import GitHubClient
from phantomstars.heuristics import score_user
from phantomstars.logging_config import setup_logging
from phantomstars.models import (
    AnalysisMode,
    Classification,
    EngagementEvent,
    RepoReport,
    SuspicionScore,
)
from phantomstars.notifier import notify_all
from phantomstars.reporter import update_readme
from phantomstars.storage import append_reports, append_suspects, iter_records, load_allowlist

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
    analysis_mode: AnalysisMode,
    scanned_repos: set[str] | None = None,
    historical_likely_fake_dates: dict[str, set[str]] | None = None,
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
    targeted = (
        scanned_repos
        if scanned_repos is not None
        else set(repo_likely) | set(repo_suspicious)
    )
    prior_history = historical_likely_fake_dates or {}
    for repo in targeted:
        repo_users = repo_all_users.get(repo, set())
        total_engagers = len(repo_users)
        likely = repo_likely[repo]
        suspicious = repo_suspicious[repo]
        fakeness_ratio = round(likely / total_engagers, 3) if total_engagers else 0.0
        known_likely_fake = sum(1 for login in repo_users if login in prior_history)
        repeat_offenders = sum(
            1 for login in repo_users if len(prior_history.get(login, set())) >= 2
        )
        known_likely_fake_ratio = (
            round(known_likely_fake / total_engagers, 3) if total_engagers else 0.0
        )
        reports.append(
            RepoReport(
                full_name=repo,
                total_scanned=total_engagers,
                likely_fake=likely,
                suspicious=suspicious,
                fakeness_ratio=fakeness_ratio,
                known_likely_fake=known_likely_fake,
                known_likely_fake_ratio=known_likely_fake_ratio,
                repeat_offenders=repeat_offenders,
                classification=_classify_repo(fakeness_ratio),
                campaign_count=len(repo_campaigns[repo]),
                analysis_mode=analysis_mode,
                scan_date=scan_date,
            )
        )

    return sorted(reports, key=lambda r: r.likely_fake, reverse=True)


def _load_prior_likely_fake_history(path: Path) -> dict[str, set[str]]:
    """Return login -> prior scan dates for accounts already labeled likely_fake."""
    history: dict[str, set[str]] = defaultdict(set)
    for record in iter_records(path):
        if record.get("classification") != "likely_fake":
            continue
        login = str(record.get("login", "")).strip()
        scan_date = str(record.get("scan_date", "")).strip()
        if login and scan_date:
            history[login].add(scan_date)
    return dict(history)


def _read_github_token() -> str:
    token = os.environ.get("GH_TOKEN", "").strip()
    if not token:
        raise RuntimeError("GH_TOKEN is required. Set it in the environment before running.")
    return token


def _parse_target_repo() -> str | None:
    raw = os.environ.get("PHANTOMSTARS_TARGET_REPO", "").strip()
    if not raw:
        return None
    parts = raw.split("/")
    if len(parts) != 2 or not all(parts):
        raise ValueError(
            "PHANTOMSTARS_TARGET_REPO must be set as 'owner/repo' when targeting one repo"
        )
    return raw


def _parse_analysis_mode() -> AnalysisMode:
    raw = os.environ.get("PHANTOMSTARS_REQUEST_DEPTH", "").strip().lower()
    if raw in {"", RECENT_ANALYSIS_MODE, "recent-request"}:
        return RECENT_ANALYSIS_MODE
    if raw in {LIFETIME_ANALYSIS_MODE, "lifetime-request"}:
        return LIFETIME_ANALYSIS_MODE
    raise ValueError(
        "PHANTOMSTARS_REQUEST_DEPTH must be 'recent' or 'lifetime' for targeted runs"
    )


def _collect_repo_events(
    client: GitHubClient,
    repo_full_name: str,
    targeted_mode: bool,
    analysis_mode: AnalysisMode,
) -> list[EngagementEvent]:
    if analysis_mode == LIFETIME_ANALYSIS_MODE:
        return client.get_lifetime_engagement(repo_full_name)

    events = client.get_recent_engagement(repo_full_name)
    if not events and targeted_mode:
        for attempt in range(2, 4):
            _log.warning(
                "No engagement events returned for %s; retrying targeted fetch (%d/3)",
                repo_full_name,
                attempt,
            )
            events = client.get_recent_engagement(repo_full_name)
            if events:
                break
    return events


def _write_step_summary(
    suspects: list[SuspicionScore],
    repo_reports: list[RepoReport],
    campaign_map: dict[str, str],
    scan_date: str,
    analysis_mode: AnalysisMode,
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
        f"| Analysis mode | `{analysis_mode}` |",
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
            "| Repo | Engagers | Likely Fake | Known Fake % | Fakeness % | Campaigns |",
            "|------|----------|-------------|--------------|------------|-----------|",
        ]
        for r in repo_reports[:15]:
            pct = f"{r.fakeness_ratio * 100:.1f}%"
            known_pct = f"{r.known_likely_fake_ratio * 100:.1f}%"
            flag = " :warning:" if r.classification == "likely_fake" else ""
            lines.append(
                f"| [{r.full_name}](https://github.com/{r.full_name}){flag}"
                f" | {r.total_scanned} | {r.likely_fake} | {known_pct}"
                f" | {pct} | {r.campaign_count} |"
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
    """Run the full daily or targeted phantomstars scan pipeline."""
    setup_logging()
    gh_token = _read_github_token()
    scan_date = datetime.now(UTC).date().isoformat()
    suspects_path = Path(SUSPECTS_FILE)
    repos_path = Path(REPOS_FILE)
    client = GitHubClient(token=gh_token)
    target_repo = _parse_target_repo()
    analysis_mode = _parse_analysis_mode() if target_repo is not None else RECENT_ANALYSIS_MODE
    prior_likely_fake_history = _load_prior_likely_fake_history(suspects_path)
    _log.info("Prior likely_fake accounts in ledger: %d", len(prior_likely_fake_history))

    # 1. Collect repos to scan from both sources, or force one target repo.
    repo_set: set[str] = set()
    if target_repo is not None:
        repo_set.add(target_repo)
        _log.info("Targeted repo mode enabled: %s (%s)", target_repo, analysis_mode)
    else:
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
        flat_events.extend(
            _collect_repo_events(
                client,
                repo,
                targeted_mode=target_repo is not None,
                analysis_mode=analysis_mode,
            )
        )
    _log.info("Total engagement events: %d", len(flat_events))

    # 3. Fetch user profiles for unique logins
    logins = list({ev.user_login for ev in flat_events})
    _log.info("Unique users to profile: %d", len(logins))
    if analysis_mode == LIFETIME_ANALYSIS_MODE:
        profiles = client.batch_fetch_profiles_for_lifetime(logins)
    else:
        profiles = client.batch_fetch_profiles(logins)
    _log.info("Profiles fetched: %d", len(profiles))

    # 4. Score every user
    scores: dict[str, SuspicionScore] = {
        login: score_user(profile, scan_date, analysis_mode) for login, profile in profiles.items()
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
    repo_reports = _build_repo_reports(
        final_scores,
        flat_events,
        scan_date,
        analysis_mode,
        scanned_repos=repo_set if target_repo is not None else None,
        historical_likely_fake_dates=prior_likely_fake_history,
    )
    _log.info(
        "Repo reports: %d targeted repos (%d likely_fake classification)",
        len(repo_reports),
        sum(1 for r in repo_reports if r.classification == "likely_fake"),
    )
    append_reports(repo_reports, repos_path)

    # 10. Update README dashboard
    update_readme(suspects_path, repos_path)

    # 11. Create/update GitHub Issues for targeted repos
    notify_all(client, repo_reports, suspects)

    # 12. Write GitHub Actions step summary
    _write_step_summary(suspects, repo_reports, campaign_map, scan_date, analysis_mode)

    _log.info("Scan complete for %s", scan_date)


if __name__ == "__main__":
    main()
