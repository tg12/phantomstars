# phantomstars | JS Labs -- https://labs.jamessawyer.co.uk/
# AI Slop Intelligence -- https://labs.jamessawyer.co.uk/ai-slop-intelligence-dashboards/
# Apache-2.0 -- https://github.com/tg12/phantomstars
"""README dashboard injector. Rewrites content between marker comments."""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path

from phantomstars.config import README_END_MARKER, README_PATH, README_START_MARKER
from phantomstars.storage import load_all

_log = logging.getLogger(__name__)

_REPO_START_MARKER = "<!-- REPO_STATS:START -->"
_REPO_END_MARKER = "<!-- REPO_STATS:END -->"

_DAILY_HEADER = (
    "| Date | Scanned | Likely Fake | Suspicious | Campaigns | New Fakes (24h) |\n"
    "|------|---------|-------------|------------|-----------|-----------------|"
)

_REPO_TABLE_HEADER = (
    "| Repo | Engagers | Likely Fake | Known Fake % | Fakeness % | Campaigns |\n"
    "|------|----------|-------------|--------------|------------|-----------|"
)

Record = dict[str, object]


def _build_daily_table(records: list[Record]) -> str:
    by_date: dict[str, list[Record]] = defaultdict(list)
    for r in records:
        date = str(r.get("scan_date", "unknown"))
        by_date[date].append(r)

    seen_logins: set[str] = set()
    rows = []
    for date in sorted(by_date.keys())[-30:]:
        day = by_date[date]
        likely_fake_logins = {
            str(r["login"]) for r in day if r.get("classification") == "likely_fake"
        }
        new_fakes = len(likely_fake_logins - seen_logins)
        seen_logins.update(str(r["login"]) for r in day)

        scanned = len(day)
        likely = len(likely_fake_logins)
        suspicious = sum(1 for r in day if r.get("classification") == "suspicious")
        campaigns = len({r.get("campaign_id") for r in day if r.get("campaign_id")})
        rows.append(f"| {date} | {scanned} | {likely} | {suspicious} | {campaigns} | {new_fakes} |")

    rows.reverse()
    if not rows:
        return f"{_DAILY_HEADER}\n| -- | -- | -- | -- | -- | -- |"
    return f"{_DAILY_HEADER}\n" + "\n".join(rows)


def _build_repo_table(repo_records: list[Record], scan_date: str) -> str:
    today = [r for r in repo_records if r.get("scan_date") == scan_date]
    if not today:
        return f"{_REPO_TABLE_HEADER}\n| *No data for {scan_date}* | — | — | — | — |"

    today_sorted = sorted(
        today,
        key=lambda r: (r.get("likely_fake", 0), r.get("fakeness_ratio", 0.0)),
        reverse=True,
    )[:25]

    rows = []
    for r in today_sorted:
        repo = r.get("full_name", "unknown")
        total = r.get("total_scanned", 0)
        likely = r.get("likely_fake", 0)
        known_ratio = r.get("known_likely_fake_ratio", 0.0)
        ratio = r.get("fakeness_ratio", 0.0)
        known_pct = (
            f"{(known_ratio if isinstance(known_ratio, float) else float(str(known_ratio))) * 100:.1f}%"
        )
        pct = f"{(ratio if isinstance(ratio, float) else float(str(ratio))) * 100:.1f}%"
        campaigns = r.get("campaign_count", 0)
        rows.append(f"| {repo} | {total} | {likely} | {known_pct} | {pct} | {campaigns} |")

    return f"{_REPO_TABLE_HEADER}\n" + "\n".join(rows)


def _inject_block(content: str, start: str, end: str, block: str) -> str:
    if start not in content:
        _log.warning("README marker '%s' not found; skipping block", start)
        return content
    s = content.index(start)
    e = content.index(end) + len(end)
    return content[:s] + f"{start}\n{block}\n{end}" + content[e:]


def update_readme(
    suspects_path: Path,
    repos_path: Path | None = None,
    readme_path: Path = Path(README_PATH),
) -> None:
    if not readme_path.exists():
        _log.warning("README not found at %s", readme_path)
        return

    content = readme_path.read_text(encoding="utf-8")

    suspect_records = load_all(suspects_path)
    daily_table = _build_daily_table(suspect_records)
    content = _inject_block(content, README_START_MARKER, README_END_MARKER, daily_table)

    if repos_path is not None and repos_path.exists():
        repo_records = load_all(repos_path)
        if repo_records:
            scan_date = str(max(r.get("scan_date", "") for r in repo_records))
            repo_table = _build_repo_table(repo_records, scan_date)
            content = _inject_block(content, _REPO_START_MARKER, _REPO_END_MARKER, repo_table)

    readme_path.write_text(content, encoding="utf-8")
    _log.info("README dashboard updated")
