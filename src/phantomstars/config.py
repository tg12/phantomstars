"""Top-level constants. No argparse, no env var parsing."""
from __future__ import annotations

GITHUB_API_BASE: str = "https://api.github.com"
GITHUB_GRAPHQL_URL: str = "https://api.github.com/graphql"
GITHUB_TRENDING_URL: str = "https://github.com/trending"

# Scan scope
LOOKBACK_HOURS: int = 24
MIN_STARS_NEW_REPO: int = 5       # search API filter for new repos
MAX_NEW_REPOS: int = 100          # circuit breaker for search results
MAX_EVENTS_PER_REPO: int = 300    # Events API hard cap

# Scoring weights (must sum to 1.0)
WEIGHT_ACCOUNT_AGE: float = 0.35
WEIGHT_PROFILE: float = 0.30
WEIGHT_REPO_PATTERN: float = 0.25
WEIGHT_ACTIVITY: float = 0.10

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
GRAPHQL_BATCH_SIZE: int = 50
RATE_LIMIT_PAUSE_THRESHOLD: int = 250  # remaining requests before pausing

# Storage
DATA_DIR: str = "data"
SUSPECTS_FILE: str = "data/suspects.jsonl"

# README injection markers
README_START_MARKER: str = "<!-- STATS:START -->"
README_END_MARKER: str = "<!-- STATS:END -->"
README_PATH: str = "README.md"
