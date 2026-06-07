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
  A <a href="https://labs.jamessawyer.co.uk/">JS Labs</a> project &mdash;
  part of the <a href="https://labs.jamessawyer.co.uk/ai-slop-intelligence-dashboards/">AI Slop Intelligence</a> initiative.<br>
  Runs every day. Scores every suspicious account. Detects coordinated bot campaigns.<br>
  Files issues directly on compromised repos so maintainers can act.
</p>

---

<p align="center"><strong>Support this project</strong></p>

<p align="center">
  <code>BTC</code> &nbsp; <code>3QjWqhQbHdHgWeYHTpmorP8Pe1wgDjJy54</code><br>
  <code>ETH</code> &nbsp; <code>0x5851e6145F4773d1585b8686095FB16E368a4dA1</code><br>
  <code>ZEC</code> &nbsp; <code>t1KSR5YkNPbjqRSCoLKo5AddFWdm9Kzxh1B</code>
</p>

---

## Why this exists

GitHub stars are a trust signal. They are how developers decide what to evaluate, what to depend on, and what to recommend. That signal is being systematically corrupted.

During the AI boom of 2024-2026, an industry of bot farms emerged to manufacture credibility for low-quality, often malicious repositories. A project with 800 stars in 48 hours reads as legitimate to a developer scanning search results. That's the point. The goal of fake engagement isn't the stars themselves; it's the social proof those stars produce, and the downstream decisions that social proof influences.

The pattern is identifiable. Accounts created the same week, no bio, no followers, no original repositories, starring the same 15 repos within a 2-hour window. Not one campaign, but dozens running simultaneously, every day, across thousands of accounts. The data shows repos where 185 out of 185 engagers are bots. A 100% fakeness ratio. Entire trending placements built on nothing.

**phantomstars** was built because this problem is tractable. The signal-to-noise ratio in GitHub's public API is, for now, still high enough that coordinated campaigns leave clear fingerprints. This project reads those fingerprints, publishes the raw data, and notifies affected repository maintainers directly.

This is part of the broader [AI Slop Intelligence](https://labs.jamessawyer.co.uk/ai-slop-intelligence-dashboards/) work at [JS Labs](https://labs.jamessawyer.co.uk/), ongoing research into the mechanics and measurable effects of low-quality AI-generated content flooding developer ecosystems. Fake engagement isn't a peripheral issue. It's the distribution mechanism that gets slop in front of real users.

---

## What it does

**phantomstars** runs a daily GitHub Actions job that:

1. Scrapes the [GitHub Trending](https://github.com/trending) page for repos gaining stars today
2. Queries the GitHub Search API for repos created in the last **7 days** with sudden star activity (the wider window catches multi-day campaigns missed by 24h-only scans)
3. Seeds additional candidate repos from recent Reddit posts in `r/osinttools` and `r/coolgithubprojects` by extracting GitHub repo links from the last **2 days**
4. Pulls recent engagement events (stars, forks) via the Events API (last 24 hours per repo)
5. Fetches the full profile of every engaging account via GraphQL: **account creation date**, follower/following counts, bio, repo history
6. Scores every account against a composite heuristics model: account age, profile completeness, repository patterns, and activity history
7. Detects **coordinated campaigns** using timestamp clustering and union-find: clusters of suspicious accounts that engaged within a 3-hour window
8. Applies the false-positive allowlist before ledger writes, repo-level ratios, dashboards, and notifications so every visible metric uses the same population
9. Appends all suspects to an append-only JSONL ledger committed back to this repo
10. Publishes a per-repo intelligence feed showing which repos are being targeted, which discovery sources found them, and whether the Events API window was complete or capped
11. **Files GitHub issues directly on targeted repos** so maintainers see the campaign data in their own issue tracker
12. Writes a formatted scan report to the GitHub Actions job summary

No servers. No databases. No infrastructure bill.

---

## Frequently asked questions

### Does it notify the targeted repo?

**Yes.** When a repo's fakeness ratio exceeds 40% or a coordinated campaign is detected, phantomstars opens an issue directly on that repository. The issue contains the full suspect table, campaign membership, composite scores, and account creation dates: everything a maintainer needs to investigate and report to GitHub.

If issues are disabled on a targeted repo, the notification is skipped silently and recorded in the scan log.

### Can I request a check for one specific repository?

Yes.

- For a normal one-off check, submit a repo in `owner/repo` form and run a targeted scan.
- For a lifetime audit request, use the one-off lifetime mode. It is separate from the daily scan.

Why the split:

- The normal scan model is designed for recent public engagement and low operator cost.
- A lifetime audit can involve tens of thousands of stars and thousands of forks on larger repos.
- That is feasible for one-off investigation, but it is too expensive and too slow for the default daily path.
- Lifetime requests therefore run only in explicit one-off mode with guardrails.

### Can I report a false positive?

Yes. If your account appears in `data/suspects.jsonl` and you believe the classification is incorrect, [open a false positive issue](../../issues/new?template=false_positive.yml) using the provided template. Reports are reviewed manually before any allowlist addition. The allowlist is stored in `data/allowlist.txt`; accounts listed there are excluded from all future scans and from the suspects ledger.

### What is the campaign ID?

A campaign ID (e.g. `c-a3f9b2e1`) is a **deterministic 8-character hex fingerprint** derived from the SHA-256 hash of the sorted set of member logins in that campaign. The same group of accounts will produce the same campaign ID across independent scan runs, enabling longitudinal tracking. It is not a repo name, a username, or any external identifier.

**Stability:** the ID is stable as long as the campaign's member set is unchanged. If bots are added or suspended between scans, the ID changes because the membership changed. This is expected and reflects real-world drift in bot farm composition.

### Does it check account creation dates?

Yes. Every account's creation date is fetched from the GitHub GraphQL API (`createdAt` field) and stored in each suspect record as `account_created_at`. It's also the primary input to the account age score, the strongest single signal for fake accounts. Accounts created within 2 days of engaging score 1.0 on age alone.

### How confident is it?

Individual scores carry meaningful false positive rates. A new developer with a sparse profile legitimately scores 0.75+. The tool accounts for this by requiring campaign-level evidence before filing issues; a single suspicious account is not enough. A coordinated cluster of 40+ accounts, all created the same week, all scoring 0.75+, all engaging within 90 minutes, is a different matter. That's where confidence becomes actionable.

The data is always probabilistic. The issue bodies say so explicitly. The goal is to give maintainers the signal and the raw evidence to make their own judgement.

---

## Live dashboard

<!-- STATS:START -->
| Date | Scanned | Likely Fake | Suspicious | Campaigns | New Fakes (24h) |
|------|---------|-------------|------------|-----------|-----------------|
| 2026-06-07 | 1797 | 658 | 1139 | 30 | 618 |
| 2026-06-06 | 2625 | 712 | 1913 | 40 | 620 |
| 2026-06-05 | 2403 | 673 | 1730 | 53 | 617 |
| 2026-06-04 | 2237 | 441 | 1796 | 41 | 367 |
| 2026-06-03 | 2331 | 488 | 1843 | 53 | 431 |
| 2026-06-02 | 2795 | 773 | 2022 | 37 | 616 |
| 2026-06-01 | 2490 | 533 | 1957 | 39 | 355 |
| 2026-05-31 | 2302 | 458 | 1844 | 32 | 280 |
| 2026-05-30 | 2576 | 530 | 2046 | 20 | 356 |
| 2026-05-29 | 2838 | 733 | 2105 | 42 | 369 |
| 2026-05-28 | 2748 | 694 | 2054 | 39 | 396 |
| 2026-05-27 | 2193 | 560 | 1633 | 32 | 491 |
| 2026-05-26 | 1930 | 236 | 1694 | 43 | 190 |
| 2026-05-25 | 1526 | 214 | 1312 | 32 | 158 |
| 2026-05-24 | 2170 | 358 | 1812 | 39 | 265 |
| 2026-05-23 | 2548 | 426 | 2122 | 43 | 317 |
| 2026-05-22 | 2318 | 340 | 1978 | 47 | 247 |
| 2026-05-21 | 1981 | 348 | 1633 | 25 | 277 |
| 2026-05-20 | 1613 | 268 | 1345 | 23 | 163 |
| 2026-05-19 | 5463 | 630 | 4121 | 67 | 442 |
| 2026-05-18 | 8838 | 670 | 7950 | 128 | 340 |
| 2026-05-17 | 8015 | 831 | 5709 | 82 | 831 |
<!-- STATS:END -->

---

## Today's most-targeted repos

<!-- REPO_STATS:START -->
| Repo | Engagers | Likely Fake | Known Fake % | Fakeness % | Campaigns | Coverage | Sources |
|------|----------|-------------|--------------|------------|-----------|----------|---------|
| rolandojesus6666-star/system-repair-tool-2 | 95 | 95 | 0.0% | 100.0% | 1 | complete | github_search_recent |
| tupopacherryy9-cloud/metamask-openclaw-desktop | 95 | 95 | 0.0% | 100.0% | 1 | complete | github_search_recent |
| souzazuzucalhlr/sketchfab-downloader-utility | 95 | 95 | 0.0% | 100.0% | 1 | complete | github_search_recent |
| joseflachendro/DrFone-Screen-Unlock-ToolKit-2 | 95 | 95 | 0.0% | 100.0% | 1 | complete | github_search_recent |
| junjie8/robloxaccountmanager-desktop-app | 75 | 75 | 0.0% | 100.0% | 1 | complete | github_search_recent |
| violadunnigan83888912091/Tomadach-PC-2026-M2 | 75 | 75 | 0.0% | 100.0% | 1 | complete | github_search_recent |
| Flavian2222/lunarclientminecraft-windows-installer | 75 | 75 | 0.0% | 100.0% | 1 | complete | github_search_recent |
| Dogexxxe/optiscalerclient-desktop-setup | 75 | 75 | 0.0% | 100.0% | 1 | complete | github_search_recent |
| alfhamdy515-svg/monkemodmanager-windows-installer-2 | 75 | 75 | 0.0% | 100.0% | 1 | complete | github_search_recent |
| mavi9727stoke6893/Acrobat-Version-Pro-2 | 75 | 75 | 0.0% | 100.0% | 1 | complete | github_search_recent |
| melojuve31-source/kahoottoolsai-desktop-app | 75 | 75 | 0.0% | 100.0% | 1 | complete | github_search_recent |
| Aluccard992ad/twitchdropminer-desktop-setup | 75 | 75 | 0.0% | 100.0% | 1 | complete | github_search_recent |
| gerardapennant96075336582/CapC-Pro-2 | 76 | 75 | 0.0% | 98.7% | 1 | complete | github_search_recent |
| aaviasulin123-design/kms-pico-latest-m6 | 76 | 75 | 0.0% | 98.7% | 1 | complete | github_search_recent |
| rosalynsheler19155568057/ComfyUI-Center | 70 | 70 | 0.0% | 100.0% | 1 | complete | github_search_recent |
| tabethasaucier88944885816/Voidstrap-PetSimulator-Hub | 70 | 70 | 0.0% | 100.0% | 1 | complete | github_search_recent |
| germainenarvaez46414207185/HomeAssistant-V26 | 70 | 70 | 0.0% | 100.0% | 1 | complete | github_search_recent |
| angelikapaup18086645729/Godot-Center | 70 | 70 | 0.0% | 100.0% | 1 | complete | github_search_recent |
| georgemccloy72990017530/TikTok-Live-RecorderV26 | 70 | 70 | 0.0% | 100.0% | 1 | complete | github_search_recent |
| c873089902979/NS-FW-AI-Image-and-Video-Generator-Uncens | 65 | 60 | 0.0% | 92.3% | 1 | complete | github_search_recent |
| Trade-of-Economics-in-Warsaw/market-sniping-trading-bot | 53 | 43 | 49.1% | 81.1% | 1 | complete | github_search_recent |
| best-spicy-ai/ai-naughty-tools | 129 | 39 | 9.3% | 30.2% | 1 | complete | github_search_recent |
| VoidSignals/Polymarket-trading-bot | 43 | 36 | 37.2% | 83.7% | 1 | complete | github_search_recent |
| sveltejs/svelte | 232 | 25 | 0.9% | 10.8% | 1 | complete | github_trending |
| obra/superpowers | 291 | 20 | 0.0% | 6.9% | 1 | complete | github_trending |
<!-- REPO_STATS:END -->

---

## Scoring model

Each account receives a composite suspicion score (0.0 = clean, 1.0 = likely fake) from four signals:

| Signal | Weight | Measurement |
|--------|--------|-------------|
| Account age | 35% | `< 2 days` → 1.00 &middot; `< 7 days` → 0.90 &middot; `< 30 days` → 0.55 &middot; `< 90 days` → 0.20 &middot; older → 0.00 |
| Profile completeness | 30% | Points for: no bio (+0.25), no location (+0.15), no company (+0.10), zero followers (+0.30), zero following (+0.10), bot-pattern username (+0.20) |
| Repository pattern | 25% | Zero repos → 0.90 &middot; all repos are forks → 0.80 &middot; >85% fork ratio → 0.55 |
| Activity history | 10% | Accounts >14 days old with zero repos + zero social graph → 0.80 (ghost accounts). Zero repos only → 0.60. All-forks + no social graph → 0.50 |

**Classification thresholds:**

| Score | Classification |
|-------|---------------|
| &ge; 0.75 | `likely_fake` |
| &ge; 0.45 | `suspicious` |
| < 0.45 | `clean` (not stored) |

### Campaign detection

A **campaign** is a group of &ge; 4 suspicious accounts that all engaged with the same repo within a 3-hour window. The algorithm uses union-find to build connected components; accounts that co-engaged within the window are merged, and any component above the minimum size is flagged as a coordinated campaign.

Campaign IDs are stable SHA-256 fingerprints of the sorted member set. The same campaign detected on consecutive days will have the same ID as long as membership is unchanged.

**Why campaigns are the real signal:** Individual scores have meaningful false positive rates. A new developer with a sparse profile can score 0.80 alone. Forty accounts all scoring 0.75+, created within the same week, all starring the same repo within 90 minutes, is not a coincidence. The campaign signal is where the data becomes actionable: the difference between a suspicious data point and evidence of a coordinated operation.

---

## Data format

All findings are committed to [`data/suspects.jsonl`](data/suspects.jsonl) and [`data/repos.jsonl`](data/repos.jsonl), one JSON record per line, append-only. The GitHub Actions job summary (visible in the Actions UI after each run) provides a formatted per-scan report.

**suspects.jsonl** — one record per flagged account per scan:
```json
{
  "login": "user98432",
  "account_age_score": 0.9,
  "profile_score": 0.8,
  "repo_pattern_score": 0.8,
  "activity_score": 0.85,
  "composite": 0.842,
  "classification": "likely_fake",
  "campaign_id": "c-a3f9b2e1",
  "scan_date": "2026-05-17",
  "account_created_at": "2026-05-15",
  "target_repos": ["owner/repo-a", "owner/repo-b"]
}
```

**repos.jsonl** — one record per targeted repo per scan:
```json
{
  "full_name": "owner/suspicious-repo",
  "total_scanned": 87,
  "likely_fake": 62,
  "suspicious": 18,
  "known_likely_fake": 27,
  "known_likely_fake_ratio": 0.310,
  "repeat_offenders": 11,
  "allowlisted_excluded": 3,
  "fakeness_ratio": 0.713,
  "classification": "likely_fake",
  "campaign_count": 3,
  "discovery_sources": ["github_search_recent", "reddit_osinttools"],
  "event_sample_complete": false,
  "scan_date": "2026-05-17"
}
```

**Query examples:**

```bash
# All likely_fake accounts from today
jq 'select(.scan_date == "2026-05-17" and .classification == "likely_fake") | .login' data/suspects.jsonl

# Accounts created in the last 3 days that were flagged
jq 'select(.account_created_at >= "2026-05-14") | [.login, .account_created_at, .classification] | @tsv' -r data/suspects.jsonl

# Which repos were targeted today, sorted by fakeness ratio
jq 'select(.scan_date == "2026-05-17") | [.full_name, .fakeness_ratio, .likely_fake] | @tsv' -r data/repos.jsonl | sort -t$'\''\t'\'' -k2 -rn

# Repos with the highest recycled-bot share from previously seen likely_fake accounts
jq 'select(.scan_date == "2026-05-17") | [.full_name, .known_likely_fake_ratio, .repeat_offenders] | @tsv' -r data/repos.jsonl | sort -t$'\''\t'\'' -k2 -rn

# All members of a specific campaign
jq 'select(.campaign_id == "c-a3f9b2e1") | [.login, .account_created_at, .composite] | @tsv' -r data/suspects.jsonl

# Repos a specific account targeted
jq 'select(.login == "user98432") | .target_repos[]' data/suspects.jsonl

# High-confidence repos: fakeness ratio above 60%
jq 'select(.fakeness_ratio >= 0.6) | [.full_name, .fakeness_ratio, .campaign_count] | @tsv' -r data/repos.jsonl | sort -t$'\t' -k2 -rn
```

---

## Setup

### 1. Fork this repo

Your fork owns the data. Results are committed back to `data/suspects.jsonl` and `data/repos.jsonl` on your fork after every daily run.

### 2. Add a GitHub PAT secret

Create a **classic** Personal Access Token with scopes:
- `public_repo`: read public repo events and stargazers, create issues on public repos
- `read:user`: fetch user profiles via GraphQL

**Settings &rarr; Secrets and variables &rarr; Actions &rarr; New repository secret** &rarr; name it `GH_TOKEN`.

> The default `GITHUB_TOKEN` has restricted rate limits and cannot call the user GraphQL endpoint at full capacity. A PAT is required.

### 3. Enable Actions

**Actions &rarr; Enable GitHub Actions** on your fork. The workflow runs at **07:00 UK time daily** using the `Europe/London` clock:
- **06:00 UTC** during British Summer Time
- **07:00 UTC** during Greenwich Mean Time

No extra scheduling environment variable is required. GitHub Actions cron is UTC-only, so the workflow triggers at both UTC hours and only proceeds when the local London time is 07:00. Manual trigger available via **Actions &rarr; Daily Phantom Stars Scan &rarr; Run workflow**.

After each run, the formatted scan report is visible in **Actions &rarr; [run] &rarr; Summary**.

### 4. Run locally

```bash
git clone https://github.com/YOUR_USERNAME/phantomstars.git
cd phantomstars
python -m venv venv && source venv/bin/activate
pip install -e .
GH_TOKEN=ghp_your_token python -m phantomstars.main
```

For an ad hoc local run after setup:

```bash
GH_TOKEN=ghp_your_token python -m phantomstars.main
```

To scan one repository instead of the normal discovery set:

```bash
PHANTOMSTARS_TARGET_REPO=owner/repo GH_TOKEN=ghp_your_token python -m phantomstars.main
```

### One-off requests

Users can request a one-off repo check in two ways:

1. Open the `Repo Check Request` issue template and provide the target repo plus requested depth.
2. Use **Actions -> Daily Phantom Stars Scan -> Run workflow** and optionally set:
   - `target_repo`: `owner/repo`
   - `request_depth`: `recent` or `lifetime-request`

Current behavior:

- `recent`: runs the targeted recent-engagement scan immediately.
- `lifetime-request`: runs a targeted lifetime scan across historical stars and forks for that repo only.
- The daily scheduled scan remains unchanged and continues to use the recent-engagement method.

Guardrails for lifetime mode:

- only available for explicit one-off targeted requests
- capped by configured repository-size limits before the scan starts
- slower and more API-intensive than the daily scan

---

## Project structure

```
phantomstars/
├── .github/
│   ├── workflows/daily-scan.yml       # Runs daily at 07:00 Europe/London
│   └── ISSUE_TEMPLATE/false_positive.yml
├── src/phantomstars/
│   ├── config.py                      # All constants, no argparse, no env parsing
│   ├── models.py                      # Frozen dataclasses
│   ├── github_client.py               # REST + GraphQL, tenacity retries, rate-limit aware
│   ├── heuristics.py                  # Per-user composite scoring engine
│   ├── campaigns.py                   # Timestamp clustering + union-find
│   ├── storage.py                     # JSONL append + query helpers
│   ├── reporter.py                    # README dashboard injector
│   ├── notifier.py                    # GitHub Issues notifier (files on targeted repos)
│   └── main.py                        # Orchestration entry point
├── tests/
│   ├── conftest.py
│   ├── test_heuristics.py
│   └── test_campaigns.py
├── data/
│   ├── suspects.jsonl                 # Append-only account findings ledger
│   ├── repos.jsonl                    # Append-only per-repo intelligence
│   └── allowlist.txt                  # Accounts excluded from future scans
└── pyproject.toml
```

---

## Limitations and known failure modes

- **Events API cap:** maximum 300 recent events per repo. Repos with thousands of stars in a day have partial coverage.
- **Coverage flag:** repos that hit the 300-event cap are marked as `capped` in reports and dashboards; ratios on those repos are conservative samples, not full-day counts.
- **Search index lag:** GitHub's search index is eventually consistent. Repos created seconds before the scan boundary may be missed.
- **Heuristic drift:** Bot operators adapt. Score weights may require periodic tuning; adjust constants in `config.py`.
- **Individual false positives:** A new developer with a sparse profile scores 0.75+ in isolation. Campaign membership is the high-confidence signal.
- **Campaign ID drift:** If a bot farm's membership changes between scans (bots suspended, new bots added), the campaign ID changes. This reflects actual campaign evolution, not a bug.
- **Rate limits:** 5,000 API requests/hour on an authenticated PAT. Well within limits for standard trending page sizes.
- **Issues disabled:** Some targeted repos disable issues. Notifications for those repos are skipped silently.

---

## False positive process

If your account appears in `data/suspects.jsonl` and you believe it is incorrectly classified:

1. Find your entry: `jq 'select(.login == "YOUR_LOGIN")' data/suspects.jsonl`
2. [Open a false positive issue](../../issues/new?template=false_positive.yml) with your login, classification, scan date, and explanation
3. Reports are reviewed manually. Verified false positives are added to `data/allowlist.txt` and excluded from all future scans, repo ratios, and issue notifications.

Note: opening an issue does not modify or remove any existing data. The suspects ledger is append-only. The allowlist only affects future scans.

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

This tool performs read-only analysis of public GitHub data using the official GitHub API. Where issues are filed on targeted repositories, they contain probabilistic findings and are clearly labelled as automated. Findings are indicators, not accusations. False positives exist and are expected.

Built with AI as a coding partner, in response to an ecosystem problem created in part by AI.

---

## License

Apache 2.0. See [LICENSE](LICENSE)

---

## Author

Built by **tg12** &middot; [GitHub](https://github.com/tg12)

A **[JS Labs](https://labs.jamessawyer.co.uk/)** project &middot; [AI Slop Intelligence Dashboards](https://labs.jamessawyer.co.uk/ai-slop-intelligence-dashboards/)
