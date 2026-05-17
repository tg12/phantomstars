# phantomstars | JS Labs -- https://labs.jamessawyer.co.uk/
# AI Slop Intelligence -- https://labs.jamessawyer.co.uk/ai-slop-intelligence-dashboards/
# Apache-2.0 -- https://github.com/tg12/phantomstars
"""JSONL append-only storage. No binary formats, no migrations."""

from __future__ import annotations

import dataclasses
import json
import logging
from pathlib import Path

from phantomstars.models import RepoReport, SuspicionScore

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
    with path.open("a", encoding="utf-8") as fh:
        for score in suspects:
            fh.write(json.dumps(dataclasses.asdict(score)) + "\n")
    _log.info("Appended %d suspect records to %s", len(suspects), path)


def append_reports(reports: list[RepoReport], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for report in reports:
            fh.write(json.dumps(dataclasses.asdict(report)) + "\n")
    _log.info("Appended %d repo reports to %s", len(reports), path)


def load_all(path: Path) -> list[dict]:  # type: ignore[type-arg]
    if not path.exists():
        return []
    records = []
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                _log.warning("Corrupt JSONL at line %d: %s", lineno, exc)
    return records
