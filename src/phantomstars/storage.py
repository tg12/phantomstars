# phantomstars | JS Labs -- https://labs.jamessawyer.co.uk/
# AI Slop Intelligence -- https://labs.jamessawyer.co.uk/ai-slop-intelligence-dashboards/
# Apache-2.0 -- https://github.com/tg12/phantomstars
"""JSONL append-only storage. No binary formats, no migrations."""

from __future__ import annotations

import dataclasses
import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

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


def iter_records(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                _log.warning("Corrupt JSONL at line %d: %s", lineno, exc)
                continue
            if isinstance(raw, dict):
                yield raw
            else:
                _log.warning("Unexpected non-object JSONL at line %d", lineno)


def load_all(path: Path) -> list[dict[str, Any]]:
    return list(iter_records(path))
