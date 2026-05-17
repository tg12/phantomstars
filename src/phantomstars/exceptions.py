"""Domain exceptions."""

from __future__ import annotations


class PhantomStarsError(Exception):
    """Base error."""


class RateLimitError(PhantomStarsError):
    """GitHub rate limit exhausted."""

    def __init__(self, reset_at: int) -> None:
        super().__init__(f"Rate limit exhausted, resets at unix ts {reset_at}")
        self.reset_at = reset_at


class TrendingParseError(PhantomStarsError):
    """Failed to extract repos from the trending page HTML."""
