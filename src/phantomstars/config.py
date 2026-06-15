# phantomstars | JS Labs -- https://labs.jamessawyer.co.uk/
# AI Slop Intelligence -- https://labs.jamessawyer.co.uk/ai-slop-intelligence-dashboards/
# Apache-2.0 -- https://github.com/tg12/phantomstars
"""Top-level constants. No argparse, no env var parsing."""

from __future__ import annotations

GITHUB_API_BASE: str = "https://api.github.com"
GITHUB_GRAPHQL_URL: str = "https://api.github.com/graphql"
GITHUB_TRENDING_URL: str = "https://github.com/trending"
REDDIT_BASE_URL: str = "https://www.reddit.com"

RECENT_ANALYSIS_MODE: str = "recent"
LIFETIME_ANALYSIS_MODE: str = "lifetime"

# Scan scope
LOOKBACK_HOURS: int = 24  # events window — how far back to pull stars/forks
REPO_DISCOVERY_DAYS: int = 7  # repo search window — catch multi-day campaigns
MIN_STARS_NEW_REPO: int = 50  # star floor for new-repo discovery (raised: reduces noise)
MAX_NEW_REPOS: int = 200  # circuit breaker for search results
MAX_EVENTS_PER_REPO: int = 300  # Events API hard cap
MAX_LIFETIME_STARGAZERS: int = 100000
MAX_LIFETIME_FORKS: int = 20000
REDDIT_DISCOVERY_DAYS: int = 2
REDDIT_POST_LIMIT: int = 100
REDDIT_SEED_SUBREDDITS: tuple[str, ...] = ("osinttools", "coolgithubprojects")

# Scoring weights (must sum to 1.0)
WEIGHT_ACCOUNT_AGE: float = 0.35
WEIGHT_PROFILE: float = 0.30
WEIGHT_REPO_PATTERN: float = 0.25
WEIGHT_ACTIVITY: float = 0.10

# Activity scoring
ACTIVITY_MIN_AGE_DAYS: int = 14  # accounts younger than this skip activity scoring

# Classification thresholds
SCORE_LIKELY_FAKE: float = 0.75
SCORE_SUSPICIOUS: float = 0.45

# Account age bands (days)
AGE_BAND_HIGH: int = 7
AGE_BAND_MED: int = 30
AGE_BAND_LOW: int = 90

# Campaign detection
MIN_CAMPAIGN_SIZE: int = 4
CAMPAIGN_WINDOW_HOURS: int = 3

# GitHub API
GRAPHQL_BATCH_SIZE: int = 30
LIFETIME_GRAPHQL_BATCH_SIZE: int = 50
RATE_LIMIT_PAUSE_THRESHOLD: int = 250  # remaining requests before pausing

# Storage
DATA_DIR: str = "data"
SUSPECTS_FILE: str = "data/suspects.jsonl"
REPOS_FILE: str = "data/repos.jsonl"

# Repo owner exclusions — large, well-known organisations whose repos are scanned
# for engagement signals but should never receive an automated issue report.
# Fake stars on these repos are still detected and stored in the ledger; they
# are simply not surfaced as GitHub issues on the host repo.
EXCLUDED_ISSUE_OWNERS: frozenset[str] = frozenset(
    {
        "microsoft",
        "google",
        "apache",
        "facebook",
        "meta",
        "aws",
        "amazon",
        "netflix",
        "twitter",
        "x",
        "apple",
        "ibm",
        "oracle",
        "salesforce",
        "adobe",
        "shopify",
        "airbnb",
        "uber",
        "lyft",
        "spotify",
        "linkedin",
        "stripe",
        "square",
        "dropbox",
        "atlassian",
        "elastic",
        "hashicorp",
        "grafana",
        "kubernetes",
        "docker",
        "golang",
        "rust-lang",
        "python",
        "nodejs",
        "mozilla",
        "torvalds",
        "github",
        "azure",
        "vercel",
        "jetbrains",
        "openai",
        "anthropics",
        "huggingface",
    }
)

# Issue notifier
MIN_FAKENESS_FOR_ISSUE: float = 0.25  # repos below this threshold are not reported as issues
MAX_ISSUES_PER_SCAN: int = 20  # cap to prevent flooding on high-activity days

# README injection markers
README_START_MARKER: str = "<!-- STATS:START -->"
README_END_MARKER: str = "<!-- STATS:END -->"
README_PATH: str = "README.md"
