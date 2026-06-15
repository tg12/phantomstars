# phantomstars | JS Labs -- https://labs.jamessawyer.co.uk/
# AI Slop Intelligence -- https://labs.jamessawyer.co.uk/ai-slop-intelligence-dashboards/
# Apache-2.0 -- https://github.com/tg12/phantomstars
"""Creates and updates GitHub issues on targeted repos for each fake-engagement finding."""

from __future__ import annotations

import logging
from collections import Counter

import requests

from phantomstars.config import (
    LIFETIME_ANALYSIS_MODE,
    LOOKBACK_HOURS,
    MAX_ISSUES_PER_SCAN,
    MIN_FAKENESS_FOR_ISSUE,
)
from phantomstars.exceptions import RateLimitError
from phantomstars.github_client import GitHubClient
from phantomstars.models import RepoReport, SuspicionScore

_log = logging.getLogger(__name__)

_SUSPECT_TABLE_LIMIT = 30
_ISSUE_TITLE = "[phantomstars] Automated fake-engagement analysis — for information only"
_PHANTOMSTARS_REPO = "tg12/phantomstars"


def _scan_window_label(report: RepoReport) -> str:
    if report.analysis_mode == LIFETIME_ANALYSIS_MODE:
        return "lifetime star/fork history"
    return f"{LOOKBACK_HOURS} h window"


def _coverage_label(report: RepoReport) -> str:
    if report.analysis_mode == LIFETIME_ANALYSIS_MODE:
        return "complete"
    if report.event_sample_complete:
        return "complete"
    return "capped by the recent-events API limit (300 events)"


def _suspect_table(suspects: list[SuspicionScore]) -> str:
    top = sorted(suspects, key=lambda s: s.composite, reverse=True)[:_SUSPECT_TABLE_LIMIT]
    header = (
        "| Account | Created | Score | Classification | Campaign |\n"
        "|---------|---------|-------|----------------|----------|"
    )
    rows = []
    for s in top:
        link = f"[{s.login}](https://github.com/{s.login})"
        campaign = f"`{s.campaign_id}`" if s.campaign_id else "--"
        rows.append(
            f"| {link} | {s.account_created_at} | {s.composite:.3f}"
            f" | {s.classification} | {campaign} |"
        )
    note = (
        f"\n\n*Showing top {_SUSPECT_TABLE_LIMIT} of {len(suspects)} suspects by composite score.*"
        if len(suspects) > _SUSPECT_TABLE_LIMIT
        else ""
    )
    return f"{header}\n" + "\n".join(rows) + note


def _campaign_table(suspects: list[SuspicionScore]) -> str:
    sizes = Counter(s.campaign_id for s in suspects if s.campaign_id)
    if not sizes:
        return "*No coordinated campaigns detected in this scan.*"
    header = "| Campaign ID | Members |\n|-------------|---------|"
    rows = [
        f"| `{cid}` | {count} |"
        for cid, count in sorted(sizes.items(), key=lambda x: x[1], reverse=True)
    ]
    return f"{header}\n" + "\n".join(rows)


def _issue_body(report: RepoReport, suspects: list[SuspicionScore]) -> str:
    pct = f"{report.fakeness_ratio * 100:.1f}%"
    scan_window = _scan_window_label(report)
    known_fake = (
        f"{report.known_likely_fake} ({report.known_likely_fake_ratio * 100:.1f}%)"
    )
    return f"""\
> **This issue is filed for information only.**
> It is an automated observation, not an accusation or complaint.
> No action is required from the repository owner or maintainers.
> If the findings are inaccurate, please report a false positive using the link at the bottom of this issue.

## Fake-Engagement Analysis for `{report.full_name}`

[phantomstars](https://github.com/{_PHANTOMSTARS_REPO}) has flagged statistical indicators of \
a possible fake star/fork campaign targeting this repository.

**Scan date:** {report.scan_date}

### Summary

| Metric | Value |
|--------|-------|
| Engagers scanned ({scan_window}) | {report.total_scanned} |
| Likely fake | **{report.likely_fake}** ({pct}) |
| Suspicious | {report.suspicious} |
| Previously seen likely fake | {known_fake} |
| Repeat offenders | {report.repeat_offenders} |
| Allowlisted accounts excluded | {report.allowlisted_excluded} |
| Campaigns detected | {report.campaign_count} |
| Analysis mode | `{report.analysis_mode}` |
| Discovery sources | {", ".join(report.discovery_sources) or "--"} |
| Event coverage | {_coverage_label(report)} |
| Repo classification | `{report.classification}` |

### Campaigns

{_campaign_table(suspects)}

### Suspect accounts

{_suspect_table(suspects)}

---

> **All findings are probabilistic indicators only — not accusations.**
> Individual accounts should be treated as suspicious signals, not confirmed fake actors.
> False positives are expected; scores are derived from public account metadata, not intent.
> Repo-level counts exclude accounts on the current false-positive allowlist.
>
> Automated scan by
> [phantomstars](https://github.com/{_PHANTOMSTARS_REPO}).
> [View full dataset](https://github.com/{_PHANTOMSTARS_REPO}/blob/main/data/repos.jsonl)
> [Report a false positive](https://github.com/{_PHANTOMSTARS_REPO}/issues/new?template=false_positive.yml)
"""


def _comment_body(report: RepoReport, suspects: list[SuspicionScore]) -> str:
    pct = f"{report.fakeness_ratio * 100:.1f}%"
    scan_window = _scan_window_label(report)
    known_fake = (
        f"{report.known_likely_fake} ({report.known_likely_fake_ratio * 100:.1f}%)"
    )
    return f"""\
### Scan update: {report.scan_date} — for information only

> This is an automated update to the analysis above. No action is required.

| Metric | Value |
|--------|-------|
| Engagers scanned ({scan_window}) | {report.total_scanned} |
| Likely fake | **{report.likely_fake}** ({pct}) |
| Suspicious | {report.suspicious} |
| Previously seen likely fake | {known_fake} |
| Repeat offenders | {report.repeat_offenders} |
| Allowlisted accounts excluded | {report.allowlisted_excluded} |
| Campaigns | {report.campaign_count} |
| Discovery sources | {", ".join(report.discovery_sources) or "--"} |
| Event coverage | {_coverage_label(report)} |

{_suspect_table(suspects)}
"""


def _find_existing_issue(client: GitHubClient, target_repo: str) -> int | None:
    """Search the target repo for an existing open phantomstars issue by title."""
    try:
        return client.find_open_issue(target_repo, _ISSUE_TITLE, labels=None)
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code in (404, 410):
            return None
        raise


def notify_repo(
    client: GitHubClient,
    report: RepoReport,
    suspects: list[SuspicionScore],
) -> None:
    """Create a new issue or add a scan-update comment on the targeted external repo."""
    target = report.full_name

    try:
        existing = _find_existing_issue(client, target)
        if existing is not None:
            client.add_comment(target, existing, _comment_body(report, suspects))
            _log.info("Commented on %s#%d", target, existing)
        else:
            number = client.create_issue(target, _ISSUE_TITLE, _issue_body(report, suspects), [])
            _log.info("Created issue #%d on %s", number, target)
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else 0
        if status in (404, 410, 422):
            _log.info("Issues disabled on %s (HTTP %d) -- skipping", target, status)
        else:
            raise


def notify_all(
    client: GitHubClient,
    repo_reports: list[RepoReport],
    all_suspects: list[SuspicionScore],
    min_fakeness: float = MIN_FAKENESS_FOR_ISSUE,
    max_issues_per_scan: int = MAX_ISSUES_PER_SCAN,
) -> None:
    """Create/update issues on targeted repos, capped to avoid flooding."""
    qualifying = [
        r for r in repo_reports if r.fakeness_ratio >= min_fakeness or r.campaign_count > 0
    ]
    if len(qualifying) > max_issues_per_scan:
        _log.warning(
            "%d repos qualify for issues; capping at %d to avoid flooding",
            len(qualifying),
            max_issues_per_scan,
        )
        qualifying = qualifying[:max_issues_per_scan]

    _log.info(
        "Notifying %d repos via GitHub Issues (filing on each targeted repo)", len(qualifying)
    )

    for report in qualifying:
        repo_suspects = [
            s
            for s in all_suspects
            if report.full_name in s.target_repos and s.classification != "clean"
        ]
        try:
            notify_repo(client, report, repo_suspects)
        except (RateLimitError, requests.ConnectionError, requests.HTTPError) as exc:
            _log.error("Issue notification failed for %s: %s", report.full_name, exc)
