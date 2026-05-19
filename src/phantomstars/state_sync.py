"""Workflow state reconciliation for append-only ledgers and derived README output."""

from __future__ import annotations

from pathlib import Path

from phantomstars.reporter import update_readme


def _load_lines(path: Path) -> list[str]:
    """Return non-empty lines from a text file, preserving order."""
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _merge_append_only_lines(current_lines: list[str], scan_lines: list[str]) -> list[str]:
    """Append only unseen scan lines onto the current ledger state."""
    merged = list(current_lines)
    seen = set(current_lines)
    for line in scan_lines:
        if line in seen:
            continue
        merged.append(line)
        seen.add(line)
    return merged


def _write_lines(path: Path, lines: list[str]) -> None:
    """Write normalized newline-terminated text content."""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(lines)
    if content:
        content += "\n"
    path.write_text(content, encoding="utf-8")


def sync_generated_state(
    *,
    scan_suspects_path: Path,
    scan_repos_path: Path,
    workspace_suspects_path: Path,
    workspace_repos_path: Path,
    readme_path: Path,
) -> None:
    """Merge this run's append-only records into the latest workspace state and rebuild README."""
    merged_suspects = _merge_append_only_lines(
        _load_lines(workspace_suspects_path),
        _load_lines(scan_suspects_path),
    )
    merged_repos = _merge_append_only_lines(
        _load_lines(workspace_repos_path),
        _load_lines(scan_repos_path),
    )
    _write_lines(workspace_suspects_path, merged_suspects)
    _write_lines(workspace_repos_path, merged_repos)
    update_readme(workspace_suspects_path, workspace_repos_path, readme_path)


def sync_generated_state_from_scan_directory(scan_directory: Path) -> None:
    """Merge scan artifacts from scan_directory into the default workspace paths."""
    sync_generated_state(
        scan_suspects_path=scan_directory / "suspects.jsonl",
        scan_repos_path=scan_directory / "repos.jsonl",
        workspace_suspects_path=Path("data/suspects.jsonl"),
        workspace_repos_path=Path("data/repos.jsonl"),
        readme_path=Path("README.md"),
    )
