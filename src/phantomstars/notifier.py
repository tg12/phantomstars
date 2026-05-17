# phantomstars | JS Labs -- https://labs.jamessawyer.co.uk/
# AI Slop Intelligence -- https://labs.jamessawyer.co.uk/ai-slop-intelligence-dashboards/
# Apache-2.0 -- https://github.com/tg12/phantomstars
"""Creates and updates GitHub issues on targeted repos for each fake-engagement finding."""

from __future__ import annotations

import logging
from collections import Counter

import requests

from phantomstars.config import MAX_ISSUES_PER_SCAN, MIN_FAKENESS_FOR_ISSUE
from phantomstars.github_client import GitHubClient
from phantomstars.models import RepoReport, SuspicionScore

_log = logging.getLogger(__name__)

_SUSPECT_TABLE_LIMIT = 30
_ISSUE_TITLE = "[phantomstars] Fake engagement detected on this repository"
_PHANTOMSTARS_REPO = "tg12/phantomstars"


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
    return f"""\
## Fake Engagement Alert for `{report.full_name}`

[phantomstars]({_PHANTOMSTARS_REPO}) has detected a likely fake star/fork campaign \
targeting this repository.

**Scan date:** {report.scan_date}

### Summary

| Metric | Value |
|--------|-------|
| Engagers scanned (24 h window) | {report.total_scanned} |
| Likely fake | **{report.likely_fake}** ({pct}) |
| Suspicious | {report.suspicious} |
| Campaigns detected | {report.campaign_count} |
| Repo classification | `{report.classification}` |

### Campaigns

{_campaign_table(suspects)}

### Suspect accounts

{_suspect_table(suspects)}

---

> **All findings are probabilistic indicators, not accusations. False positives exist.**
> Individual accounts should be treated as suspicious signals, not confirmed fake actors.
>
> Automated scan by [phantomstars](https://github.com/{_PHANTOMSTARS_REPO}).
> [View full dataset](https://github.com/{_PHANTOMSTARS_REPO}/blob/main/data/repos.jsonl) \
\xb7 [Report a false positive](https://github.com/{_PHANTOMSTARS_REPO}/issues/new?template=false_positive.yml)
"""


def _comment_body(report: RepoReport, suspects: list[SuspicionScore]) -> str:
    pct = f"{report.fakeness_ratio * 100:.1f}%"
    return f"""\
### Scan update: {report.scan_date}

| Metric | Value |
|--------|-------|
| Engagers scanned (24 h) | {report.total_scanned} |
| Likely fake | **{report.likely_fake}** ({pct}) |
| Suspicious | {report.suspicious} |
| Campaigns | {report.campaign_count} |

{_suspect_table(suspects)}
"""


def _find_existing_issue(client: GitHubClient, target_repo: str) -> int | None:
    """Search the target repo for an existing open phantomstars issue by title."""
    for page in range(1, 5):
        try:
            items = client._rest_get(
                f"https://api.github.com/repos/{target_repo}/issues",
                params={
                    "state": "open",
                    "per_page": 100,
                    "page": page,
                },
            )
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code in (404, 410):
                return None
            raise
        if not isinstance(items, list) or not items:
            break
        for item in items:
            if _ISSUE_TITLE in str(item.get("title", "")):
                return int(item["number"])
    return None


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
    ps_repo: str,
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
        except Exception as exc:
            _log.error("Issue notification failed for %s: %s", report.full_name, exc)
