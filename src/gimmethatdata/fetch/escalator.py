"""Tier escalation: detect anti-bot challenges and climb to a stronger fetcher."""

from __future__ import annotations

import re
import time

from gimmethatdata.core.models import FetchAttempt, FetchResult, FetchTier
from gimmethatdata.fetch.base import Fetcher
from gimmethatdata.fetch.rate_limit import DomainRateLimiter
from gimmethatdata.fetch.tier1_httpx import FetchError
from gimmethatdata.logging_setup import get_logger

_log = get_logger(__name__)

_CHALLENGE_PATTERNS = (
    re.compile(r"Just a moment", re.IGNORECASE),
    re.compile(r"Checking your browser", re.IGNORECASE),
    re.compile(r"cf-mitigated", re.IGNORECASE),
    re.compile(r"cdn-cgi/challenge-platform", re.IGNORECASE),
    re.compile(r"turnstile", re.IGNORECASE),
    re.compile(r"__cf_chl_", re.IGNORECASE),
)

_CHALLENGE_STATUSES: frozenset[int] = frozenset({403, 429, 503})


def is_blocked(result: FetchResult) -> bool:
    """Return True if the fetch result smells like an anti-bot challenge."""
    if result.status_code in _CHALLENGE_STATUSES:
        server = (result.headers.get("server") or "").lower()
        if "cloudflare" in server or "cf-mitigated" in result.headers:
            return True
        if result.status_code == 403:
            return True
    if any(k.startswith("cf-") for k in result.headers):
        body_head = result.body[:8192].decode(result.encoding or "utf-8", errors="ignore")
        if any(pat.search(body_head) for pat in _CHALLENGE_PATTERNS):
            return True
    if result.status_code == 200 and result.body:
        body_head = result.body[:8192].decode(result.encoding or "utf-8", errors="ignore")
        if any(pat.search(body_head) for pat in _CHALLENGE_PATTERNS):
            return True
    return False


class EscalatingFetcher:
    """Walks fetchers in order, escalating on detected challenges."""

    def __init__(
        self,
        tiers: list[Fetcher],
        *,
        rate_limiter: DomainRateLimiter | None = None,
    ) -> None:
        if not tiers:
            raise ValueError("EscalatingFetcher requires at least one tier")
        self._tiers = tiers
        self._rate = rate_limiter

    async def fetch(self, url: str) -> FetchResult:
        if self._rate is not None:
            await self._rate.acquire(url)
        attempts: list[FetchAttempt] = []
        last_result: FetchResult | None = None
        for index, tier in enumerate(self._tiers):
            started = time.perf_counter()
            tier_name = type(tier).__name__
            try:
                result = await tier.fetch(url)
            except FetchError as exc:
                elapsed = int((time.perf_counter() - started) * 1000)
                attempts.append(
                    FetchAttempt(tier=exc.tier, error=str(exc), elapsed_ms=elapsed)
                )
                _log.warning("tier_failed", tier=tier_name, url=url, error=str(exc))
                continue
            attempts.extend(result.attempts)
            last_result = result
            if not is_blocked(result):
                result.attempts = attempts
                return result
            _log.info(
                "tier_blocked",
                tier=tier_name,
                status=result.status_code,
                next_tier_index=index + 1,
                url=url,
            )
        if last_result is None:
            raise FetchError(
                "all tiers failed", tier=FetchTier.HTTPX, elapsed_ms=sum(a.elapsed_ms for a in attempts)
            )
        last_result.attempts = attempts
        return last_result

    async def aclose(self) -> None:
        for tier in self._tiers:
            await tier.aclose()
