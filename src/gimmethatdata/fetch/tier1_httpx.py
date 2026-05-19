"""Tier-1 fetcher: plain async httpx with optional auth + HTTP cache."""

from __future__ import annotations

import time
from types import TracebackType

import httpx

from gimmethatdata.core.models import FetchAttempt, FetchResult, FetchTier
from gimmethatdata.fetch.auth import AuthConfig
from gimmethatdata.fetch.http_cache import HttpCache


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
        auth: AuthConfig | None = None,
        cache: HttpCache | None = None,
    ) -> None:
        headers: dict[str, str] = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if auth is not None:
            headers.update(auth.header_overrides())
        self._client = httpx.AsyncClient(
            http2=True,
            timeout=timeout_seconds,
            follow_redirects=follow_redirects,
            verify=verify_tls,
            headers=headers,
            proxy=proxy,
        )
        self._cache = cache

    async def fetch(self, url: str) -> FetchResult:
        started = time.perf_counter()
        cached = self._cache.lookup(url) if self._cache is not None else None
        request_headers = cached.conditional_headers() if cached is not None else None
        try:
            response = await self._client.get(url, headers=request_headers)
        except httpx.HTTPError as exc:
            elapsed = int((time.perf_counter() - started) * 1000)
            raise FetchError(str(exc), tier=FetchTier.HTTPX, elapsed_ms=elapsed) from exc

        elapsed = int((time.perf_counter() - started) * 1000)
        headers_map = {k.lower(): v for k, v in response.headers.items()}

        if response.status_code == 304 and cached is not None and self._cache is not None:
            body = self._cache.load_body(cached)
            attempt = FetchAttempt(
                tier=FetchTier.HTTPX, status_code=304, elapsed_ms=elapsed
            )
            return FetchResult(
                url=url,
                final_url=str(response.url),
                status_code=cached.status_code,
                headers={**cached.headers, "x-gtd-cache": "hit"},
                body=body,
                encoding="utf-8",
                tier=FetchTier.HTTPX,
                elapsed_ms=elapsed,
                attempts=[attempt],
            )

        if self._cache is not None and response.status_code == 200:
            self._cache.store(
                url,
                status_code=response.status_code,
                headers=headers_map,
                body=response.content,
            )

        attempt = FetchAttempt(
            tier=FetchTier.HTTPX, status_code=response.status_code, elapsed_ms=elapsed
        )
        return FetchResult(
            url=url,
            final_url=str(response.url),
            status_code=response.status_code,
            headers=headers_map,
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
