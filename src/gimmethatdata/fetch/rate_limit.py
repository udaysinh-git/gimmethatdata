"""Per-domain rate limiter registry."""

from __future__ import annotations

from aiolimiter import AsyncLimiter

from gimmethatdata.core.url_utils import domain_of


class DomainRateLimiter:
    """Lazy registry: one AsyncLimiter per domain, configured by RPS."""

    def __init__(self, requests_per_second: float = 2.0) -> None:
        self._rps = max(requests_per_second, 0.1)
        self._limiters: dict[str, AsyncLimiter] = {}

    def _for(self, domain: str) -> AsyncLimiter:
        limiter = self._limiters.get(domain)
        if limiter is None:
            limiter = AsyncLimiter(max_rate=self._rps, time_period=1.0)
            self._limiters[domain] = limiter
        return limiter

    async def acquire(self, url: str) -> None:
        await self._for(domain_of(url)).acquire()
