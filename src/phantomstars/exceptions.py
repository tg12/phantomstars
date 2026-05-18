# phantomstars | JS Labs -- https://labs.jamessawyer.co.uk/
# AI Slop Intelligence -- https://labs.jamessawyer.co.uk/ai-slop-intelligence-dashboards/
# Apache-2.0 -- https://github.com/tg12/phantomstars
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


class LifetimeScanLimitError(PhantomStarsError):
    """Requested lifetime audit exceeds configured safety limits."""
