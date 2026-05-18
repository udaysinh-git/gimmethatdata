"""Tier-2 fetcher: curl_cffi with Chrome TLS impersonation."""

from __future__ import annotations

import time
from types import TracebackType
from typing import Any

from gimmethatdata.core.models import FetchAttempt, FetchResult, FetchTier
from gimmethatdata.fetch.tier1_httpx import FetchError


class CurlCffiFetcher:
    """Async fetcher with browser-grade TLS fingerprint."""

    def __init__(
        self,
        *,
        user_agent: str,
        timeout_seconds: float = 30.0,
        impersonate: str = "chrome124",
        proxy: str | None = None,
    ) -> None:
        from curl_cffi.requests import AsyncSession

        self._timeout = timeout_seconds
        self._impersonate = impersonate
        self._session: Any = AsyncSession(
            timeout=timeout_seconds,
            impersonate=impersonate,  # type: ignore[arg-type]
            headers={"User-Agent": user_agent},
            proxy=proxy,
        )

    async def fetch(self, url: str) -> FetchResult:
        started = time.perf_counter()
        try:
            response = await self._session.get(url, allow_redirects=True)
        except Exception as exc:
            elapsed = int((time.perf_counter() - started) * 1000)
            raise FetchError(str(exc), tier=FetchTier.CURL_CFFI, elapsed_ms=elapsed) from exc

        elapsed = int((time.perf_counter() - started) * 1000)
        headers = {k.lower(): v for k, v in dict(response.headers).items()}
        body = response.content if isinstance(response.content, bytes) else bytes(response.content)
        attempt = FetchAttempt(
            tier=FetchTier.CURL_CFFI, status_code=response.status_code, elapsed_ms=elapsed
        )
        return FetchResult(
            url=url,
            final_url=str(response.url),
            status_code=response.status_code,
            headers=headers,
            body=body,
            encoding=response.encoding,
            tier=FetchTier.CURL_CFFI,
            elapsed_ms=elapsed,
            attempts=[attempt],
        )

    async def aclose(self) -> None:
        await self._session.close()

    async def __aenter__(self) -> CurlCffiFetcher:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()
