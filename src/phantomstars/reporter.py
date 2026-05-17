"""README dashboard injector. Rewrites content between marker comments."""
from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path

from phantomstars.config import README_END_MARKER, README_PATH, README_START_MARKER
from phantomstars.storage import load_all

_log = logging.getLogger(__name__)

_HEADER = """| Date | Scanned | Likely Fake | Suspicious | Campaigns | New Fakes (24h) |
|------|---------|-------------|------------|-----------|-----------------|"""


def _build_table(records: list[dict]) -> str:  # type: ignore[type-arg]
    by_date: dict[str, list[dict]] = defaultdict(list)  # type: ignore[type-arg]
    for r in records:
        date = r.get("scan_date", "unknown")
        by_date[date].append(r)

    rows = []
    for date in sorted(by_date.keys(), reverse=True)[:30]:
        day = by_date[date]
        scanned = len(day)
        likely = sum(1 for r in day if r.get("classification") == "likely_fake")
        suspicious = sum(1 for r in day if r.get("classification") == "suspicious")
        campaigns = len({r.get("campaign_id") for r in day if r.get("campaign_id")})

        # new fakes = accounts first seen on this date
        prev_logins: set[str] = set()
        for d2, recs in by_date.items():
            if d2 < date:
                prev_logins.update(r["login"] for r in recs)
        new_fakes = sum(
            1
            for r in day
            if r.get("classification") == "likely_fake" and r["login"] not in prev_logins
        )
        rows.append(f"| {date} | {scanned} | {likely} | {suspicious} | {campaigns} | {new_fakes} |")

    if not rows:
        return f"{_HEADER}\n| — | — | — | — | — | — |"
    return f"{_HEADER}\n" + "\n".join(rows)


def update_readme(suspects_path: Path, readme_path: Path = Path(README_PATH)) -> None:
    if not readme_path.exists():
        _log.warning("README not found at %s", readme_path)
        return

    records = load_all(suspects_path)
    table = _build_table(records)
    block = f"{README_START_MARKER}\n{table}\n{README_END_MARKER}"

    content = readme_path.read_text(encoding="utf-8")
    if README_START_MARKER not in content:
        _log.warning("README marker not found; skipping dashboard update")
        return

    start = content.index(README_START_MARKER)
    end = content.index(README_END_MARKER) + len(README_END_MARKER)
    updated = content[:start] + block + content[end:]
    readme_path.write_text(updated, encoding="utf-8")
    _log.info("README dashboard updated")
