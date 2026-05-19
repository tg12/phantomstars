"""Tests for workflow state reconciliation."""

from __future__ import annotations

from pathlib import Path

from phantomstars.state_sync import _merge_append_only_lines, sync_generated_state


def test_merge_append_only_lines_appends_only_unseen_entries() -> None:
    merged = _merge_append_only_lines(
        ['{"login":"old"}', '{"login":"shared"}'],
        ['{"login":"shared"}', '{"login":"new"}'],
    )

    assert merged == ['{"login":"old"}', '{"login":"shared"}', '{"login":"new"}']


def test_sync_generated_state_merges_ledgers_and_rebuilds_readme(tmp_path: Path) -> None:
    workspace_suspects = tmp_path / "data" / "suspects.jsonl"
    workspace_repos = tmp_path / "data" / "repos.jsonl"
    scan_suspects = tmp_path / "scan" / "suspects.jsonl"
    scan_repos = tmp_path / "scan" / "repos.jsonl"
    readme = tmp_path / "README.md"

    workspace_suspects.parent.mkdir(parents=True, exist_ok=True)
    scan_suspects.parent.mkdir(parents=True, exist_ok=True)
    workspace_suspects.write_text(
        '{"login":"repeat","classification":"likely_fake","scan_date":"2026-05-18"}\n',
        encoding="utf-8",
    )
    workspace_repos.write_text(
        '{"full_name":"owner/repo-a","total_scanned":2,"likely_fake":1,'
        '"suspicious":0,"fakeness_ratio":0.5,"known_likely_fake":0,'
        '"known_likely_fake_ratio":0.0,"repeat_offenders":0,"allowlisted_excluded":0,'
        '"classification":"likely_fake","campaign_count":1,"analysis_mode":"recent",'
        '"scan_date":"2026-05-18","discovery_sources":["github_trending"],'
        '"event_sample_complete":true}\n',
        encoding="utf-8",
    )
    scan_suspects.write_text(
        '{"login":"repeat","classification":"likely_fake","scan_date":"2026-05-18"}\n'
        '{"login":"new","classification":"likely_fake","scan_date":"2026-05-19"}\n',
        encoding="utf-8",
    )
    scan_repos.write_text(
        '{"full_name":"owner/repo-b","total_scanned":3,"likely_fake":2,'
        '"suspicious":1,"fakeness_ratio":0.667,"known_likely_fake":1,'
        '"known_likely_fake_ratio":0.333,"repeat_offenders":0,"allowlisted_excluded":0,'
        '"classification":"likely_fake","campaign_count":1,"analysis_mode":"recent",'
        '"scan_date":"2026-05-19","discovery_sources":["reddit_osinttools"],'
        '"event_sample_complete":false}\n',
        encoding="utf-8",
    )
    readme.write_text(
        "\n".join(
            [
                "# README",
                "<!-- STATS:START -->",
                "old",
                "<!-- STATS:END -->",
                "<!-- REPO_STATS:START -->",
                "old",
                "<!-- REPO_STATS:END -->",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    sync_generated_state(
        scan_suspects_path=scan_suspects,
        scan_repos_path=scan_repos,
        workspace_suspects_path=workspace_suspects,
        workspace_repos_path=workspace_repos,
        readme_path=readme,
    )

    suspects_lines = workspace_suspects.read_text(encoding="utf-8").splitlines()
    assert suspects_lines == [
        '{"login":"repeat","classification":"likely_fake","scan_date":"2026-05-18"}',
        '{"login":"new","classification":"likely_fake","scan_date":"2026-05-19"}',
    ]
    repos_lines = workspace_repos.read_text(encoding="utf-8").splitlines()
    assert len(repos_lines) == 2
    readme_text = readme.read_text(encoding="utf-8")
    assert "| 2026-05-19 | 1 | 1 | 0 | 0 | 1 |" in readme_text
    assert "reddit_osinttools" in readme_text
    assert "capped" in readme_text
