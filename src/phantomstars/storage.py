"""JSONL append-only storage. No binary formats, no migrations."""
from __future__ import annotations

import dataclasses
import json
import logging
from pathlib import Path

from phantomstars.models import SuspicionScore

_log = logging.getLogger(__name__)

ALLOWLIST_FILE: str = "data/allowlist.txt"


def load_allowlist(path: Path | None = None) -> set[str]:
    target = path or Path(ALLOWLIST_FILE)
    if not target.exists():
        return set()
    logins: set[str] = set()
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            logins.add(line.lower())
    return logins


def append_suspects(suspects: list[SuspicionScore], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="ascii") as fh:
        for score in suspects:
            fh.write(json.dumps(dataclasses.asdict(score)) + "\n")
    _log.info("Appended %d suspect records to %s", len(suspects), path)


def load_all(path: Path) -> list[dict]:  # type: ignore[type-arg]
    if not path.exists():
        return []
    records = []
    with path.open(encoding="ascii") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                _log.warning("Corrupt JSONL at line %d: %s", lineno, exc)
    return records


def load_known_fakes(path: Path) -> set[str]:
    return {r["login"] for r in load_all(path) if r.get("classification") == "likely_fake"}


def daily_stats(path: Path, scan_date: str) -> dict[str, int]:
    records = [r for r in load_all(path) if r.get("scan_date") == scan_date]
    total = len(records)
    likely = sum(1 for r in records if r.get("classification") == "likely_fake")
    suspicious = sum(1 for r in records if r.get("classification") == "suspicious")
    campaigns = len({r.get("campaign_id") for r in records if r.get("campaign_id")})
    return {
        "total": total,
        "likely_fake": likely,
        "suspicious": suspicious,
        "campaigns": campaigns,
    }
