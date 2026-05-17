<p align="center">
  <img src="https://img.shields.io/badge/phantomstars-v0.1.0-blueviolet?style=for-the-badge" alt="phantomstars">
  <img src="https://img.shields.io/badge/python-3.13-blue?style=for-the-badge" alt="Python 3.13">
  <img src="https://img.shields.io/badge/license-Apache--2.0-green?style=for-the-badge" alt="Apache 2.0">
  <img src="https://img.shields.io/badge/CI-GitHub%20Actions-orange?style=for-the-badge" alt="GitHub Actions">
  <img src="https://img.shields.io/badge/runs-daily-brightgreen?style=for-the-badge" alt="Daily">
</p>

<h1 align="center">phantomstars</h1>
<p align="center"><strong>Automated detection and tracking of fake engagement on GitHub</strong></p>
<p align="center">
  Runs every day. Scores every suspicious user. Detects coordinated bot campaigns.<br>
  Tracks fake accounts from the moment they appear on trending.
</p>

---

<p align="center"><strong>Support this project</strong></p>

<p align="center">
  <code>BTC</code> &nbsp; <code>3QjWqhQbHdHgWeYHTpmorP8Pe1wgDjJy54</code><br>
  <code>ETH</code> &nbsp; <code>0x5851e6145F4773d1585b8686095FB16E368a4dA1</code><br>
  <code>ZEC</code> &nbsp; <code>t1KSR5YkNPbjqRSCoLKo5AddFWdm9Kzxh1B</code>
</p>

---

## What it does

GitHub has a fake engagement problem. Bot farms star and fork repos to inflate popularity metrics, game the trending page, and manufacture credibility for malicious or low-quality projects. These campaigns are coordinated — dozens of accounts created on the same day, all starring the same repos within minutes of each other, with zero contribution history and empty profiles.

**phantomstars** runs a daily GitHub Actions job (free, public repo, unlimited minutes) that:

1. Scrapes the [GitHub Trending](https://github.com/trending) page for repos gaining stars today
2. Queries the GitHub Search API for repos created in the last 24 hours with sudden star activity
3. Pulls recent engagement events (stars, forks) via the Events API — newest first, stops at the 24h cutoff
4. Scores every engaging user against a composite heuristics model: account age, profile completeness, repository patterns, activity history, and username bot-patterns
5. Detects **coordinated campaigns** — clusters of suspicious accounts that engaged within a 3-hour window — using timestamp clustering and union-find, no external graph library
6. Appends all suspects to an append-only JSONL ledger committed back to this repo
7. Updates this README with a live dashboard

No servers. No databases. No infrastructure bill.

---

## Live dashboard

<!-- STATS:START -->
| Date | Scanned | Likely Fake | Suspicious | Campaigns | New Fakes (24h) |
|------|---------|-------------|------------|-----------|-----------------|
| — | — | — | — | — | — |
<!-- STATS:END -->

---

## Scoring model

Each user receives a composite suspicion score (0.0 = clean → 1.0 = fake) from four weighted signals:

| Signal | Weight | What is measured |
|--------|--------|-----------------|
| Account age | 35% | < 7 days → 0.90; < 30 days → 0.55; > 90 days → 0.00 |
| Profile completeness | 30% | Missing bio, location, zero followers, bot-pattern username |
| Repository pattern | 25% | All repos are forks, zero original repos, zero contributions |
| Activity history | 10% | Zero contributions despite account age > 14 days |

**Thresholds:**

| Score | Classification |
|-------|---------------|
| ≥ 0.75 | `likely_fake` |
| ≥ 0.45 | `suspicious` |
| < 0.45 | `clean` (not stored) |

### Campaign detection

A **campaign** is a group of ≥ 4 suspicious accounts that all engaged with the same repo within a 3-hour window. The algorithm uses union-find to build connected components — accounts that co-engaged within the window are merged, and any component above the minimum size threshold is flagged as a coordinated campaign.

Individual scores have false positives. Campaigns almost never do. A new developer with a sparse profile scores 0.80 alone. Forty accounts scoring 0.75+, created on the same day, all starring the same repo within 90 minutes, is an operation.

---

## Data format

All findings are committed to [`data/suspects.jsonl`](data/suspects.jsonl) — one JSON record per line, append-only.

```json
{
  "login": "user98432",
  "account_age_score": 0.9,
  "profile_score": 0.8,
  "repo_pattern_score": 0.8,
  "activity_score": 0.85,
  "composite": 0.842,
  "classification": "likely_fake",
  "campaign_id": "c-user98432",
  "scan_date": "2026-05-17"
}
```

Query examples:

```bash
# All likely_fake accounts
grep '"likely_fake"' data/suspects.jsonl | jq -r .login

# Campaign members grouped by campaign
jq 'select(.campaign_id != null) | [.campaign_id, .login] | @tsv' -r data/suspects.jsonl | sort

# Daily summary
jq -r .classification data/suspects.jsonl | sort | uniq -c | sort -rn

# Accounts first seen today
jq 'select(.scan_date == "2026-05-17" and .classification == "likely_fake")' data/suspects.jsonl
```

---

## Setup

### 1. Fork this repo

Your fork owns the data. Results are committed back to `data/suspects.jsonl` on your fork after every daily run.

### 2. Add a GitHub PAT secret

Create a **classic** Personal Access Token with scopes:
- `public_repo` — read public repo events and stargazers
- `read:user` — fetch user profiles via GraphQL

**Settings → Secrets and variables → Actions → New repository secret** → name it `GH_TOKEN`.

> The default `GITHUB_TOKEN` has restricted rate limits and cannot call the user search GraphQL endpoint at full capacity. Use a PAT.

### 3. Enable Actions

**Actions → Enable GitHub Actions** on your fork. The workflow runs at **07:00 UTC daily** (after GitHub resets the trending page). Manual trigger available via **Actions → Daily Phantom Stars Scan → Run workflow**.

### 4. Run locally

```bash
git clone https://github.com/YOUR_USERNAME/phantomstars.git
cd phantomstars
python -m venv venv && source venv/bin/activate
pip install -e .
GH_TOKEN=ghp_your_token python -m phantomstars.main
```

---

## Project structure

```
phantomstars/
├── .github/workflows/daily-scan.yml   # Cron: 07:00 UTC, free on public repos
├── src/phantomstars/
│   ├── config.py                      # All constants — no argparse, no env parsing
│   ├── models.py                      # Frozen dataclasses
│   ├── github_client.py               # REST + GraphQL, tenacity retries, rate-limit aware
│   ├── heuristics.py                  # Per-user composite scoring engine
│   ├── campaigns.py                   # Timestamp clustering + union-find
│   ├── storage.py                     # JSONL append + query helpers
│   ├── reporter.py                    # README dashboard injector
│   └── main.py                        # Orchestration entry point
├── tests/
│   ├── conftest.py
│   ├── test_heuristics.py
│   └── test_campaigns.py
├── data/
│   └── suspects.jsonl                 # Append-only findings ledger
└── pyproject.toml
```

---

## Limitations and known failure modes

- **Events API cap**: maximum 300 recent events per repo. Repos with thousands of stars in a day will have partial coverage.
- **Search consistency**: GitHub's search index is eventually consistent. Repos created seconds before the scan window boundary may be missed.
- **Heuristic drift**: Bot operators adapt. Score weights may require periodic tuning — adjust in `config.py`.
- **False positives on individuals**: A new developer with a sparse profile can score 0.75+ in isolation. Campaign membership is the high-confidence signal.
- **Rate limits**: 5,000 API requests/hour on an authenticated PAT. Well within limits for standard trending page sizes.

---

## Contributing

```bash
pip install -e ".[dev]"
python -m black .
python -m ruff check .
python -m mypy src
python -m pytest
```

All four must pass before a PR.

---

## Disclaimer

This tool performs read-only analysis of public GitHub data using the official GitHub API. It does not interact with, report, or modify any GitHub accounts. Findings are probabilistic indicators — not accusations. False positives exist.

Built with AI as a coding partner.

---

## License

Apache 2.0 — see [LICENSE](LICENSE)

## Author

Built by **tg12** · [GitHub](https://github.com/tg12)

A **JS Labs** project.

---

*GitHub topics to add after publishing:*
`github` · `bot-detection` · `fake-engagement` · `fake-stars` · `github-trending` · `security` · `osint` · `python` · `github-actions` · `automation` · `sybil-detection` · `astroturfing` · `spam-detection` · `github-api` · `threat-intelligence` · `open-source-intelligence` · `campaign-detection` · `infosec`
