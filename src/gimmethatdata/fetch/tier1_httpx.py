"""Tier-1 fetcher: plain async httpx."""

from __future__ import annotations

import time
from types import TracebackType

import httpx

from gimmethatdata.core.models import FetchAttempt, FetchResult, FetchTier


class HttpxFetcher:
    """Async fetcher using httpx with HTTP/2 + redirect following."""

    def __init__(
        self,
        *,
        user_agent: str,
        timeout_seconds: float = 30.0,
        follow_redirects: bool = True,
        verify_tls: bool = True,
        proxy: str | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            http2=True,
            timeout=timeout_seconds,
            follow_redirects=follow_redirects,
            verify=verify_tls,
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            proxy=proxy,
        )

    async def fetch(self, url: str) -> FetchResult:
        started = time.perf_counter()
        try:
            response = await self._client.get(url)
        except httpx.HTTPError as exc:
            elapsed = int((time.perf_counter() - started) * 1000)
            raise FetchError(str(exc), tier=FetchTier.HTTPX, elapsed_ms=elapsed) from exc

        elapsed = int((time.perf_counter() - started) * 1000)
        attempt = FetchAttempt(
            tier=FetchTier.HTTPX, status_code=response.status_code, elapsed_ms=elapsed
        )
        return FetchResult(
            url=url,
            final_url=str(response.url),
            status_code=response.status_code,
            headers={k.lower(): v for k, v in response.headers.items()},
            body=response.content,
            encoding=response.encoding,
            tier=FetchTier.HTTPX,
            elapsed_ms=elapsed,
            attempts=[attempt],
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> HttpxFetcher:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()


class FetchError(Exception):
    """Raised when a fetcher tier fails."""

    def __init__(self, message: str, *, tier: FetchTier, elapsed_ms: int) -> None:
        super().__init__(message)
        self.tier = tier
        self.elapsed_ms = elapsed_ms
