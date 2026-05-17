"""Creates and updates GitHub issues on the phantomstars repo for each targeted repo."""

from __future__ import annotations

import logging
from collections import Counter

from phantomstars.config import MAX_ISSUES_PER_SCAN, MIN_FAKENESS_FOR_ISSUE
from phantomstars.github_client import GitHubClient
from phantomstars.models import RepoReport, SuspicionScore

_log = logging.getLogger(__name__)

_LABEL_FAKE_ENGAGEMENT = "fake-engagement"
_LABEL_LIKELY_FAKE = "likely-fake"
_LABEL_CAMPAIGN = "campaign-detected"

ISSUE_LABELS: list[dict[str, str]] = [
    {
        "name": _LABEL_FAKE_ENGAGEMENT,
        "color": "d73a4a",
        "description": "Fake engagement detected on this repository",
    },
    {
        "name": _LABEL_LIKELY_FAKE,
        "color": "b60205",
        "description": "Repo classified as likely_fake (fakeness >= 40%)",
    },
    {
        "name": _LABEL_CAMPAIGN,
        "color": "e4e669",
        "description": "Coordinated bot campaign detected",
    },
]

_SUSPECT_TABLE_LIMIT = 30


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


def _issue_body(report: RepoReport, suspects: list[SuspicionScore], ps_repo: str) -> str:
    pct = f"{report.fakeness_ratio * 100:.1f}%"
    return f"""\
## Fake Engagement Detected: `{report.full_name}`

**First detected:** {report.scan_date} &nbsp;|&nbsp; \
Automated scan by [phantomstars](https://github.com/{ps_repo})

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
> [View suspects.jsonl](https://github.com/{ps_repo}/blob/main/data/suspects.jsonl) \
· [View repos.jsonl](https://github.com/{ps_repo}/blob/main/data/repos.jsonl) \
· [Report a false positive](https://github.com/{ps_repo}/issues/new?template=false_positive.yml)
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


def notify_repo(
    client: GitHubClient,
    report: RepoReport,
    suspects: list[SuspicionScore],
    ps_repo: str,
) -> None:
    """Create a new issue or add a scan-update comment to an existing one."""
    title = f"[fake-engagement] {report.full_name}"
    labels: list[str] = [_LABEL_FAKE_ENGAGEMENT]
    if report.classification == "likely_fake":
        labels.append(_LABEL_LIKELY_FAKE)
    if report.campaign_count > 0:
        labels.append(_LABEL_CAMPAIGN)

    existing = client.find_open_issue(ps_repo, report.full_name)
    if existing is not None:
        client.add_comment(ps_repo, existing, _comment_body(report, suspects))
        _log.info("Commented on issue #%d for %s", existing, report.full_name)
    else:
        number = client.create_issue(ps_repo, title, _issue_body(report, suspects, ps_repo), labels)
        _log.info("Created issue #%d for %s", number, report.full_name)


def notify_all(
    client: GitHubClient,
    repo_reports: list[RepoReport],
    all_suspects: list[SuspicionScore],
    ps_repo: str,
    min_fakeness: float = MIN_FAKENESS_FOR_ISSUE,
    max_issues_per_scan: int = MAX_ISSUES_PER_SCAN,
) -> None:
    """Create/update issues for qualifying repos, capped to avoid flooding."""
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

    _log.info("Notifying %d repos via GitHub Issues", len(qualifying))

    # Ensure all required labels exist once per scan
    if qualifying:
        client.ensure_labels(ps_repo, ISSUE_LABELS)

    # Build per-repo suspect list
    for report in qualifying:
        repo_suspects = [
            s
            for s in all_suspects
            if report.full_name in s.target_repos and s.classification != "clean"
        ]
        try:
            notify_repo(client, report, repo_suspects, ps_repo)
        except Exception as exc:
            _log.error("Issue notification failed for %s: %s", report.full_name, exc)
