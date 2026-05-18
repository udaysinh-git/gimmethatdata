"""Tier-4 fetcher: FlareSolverr HTTP shim (opt-in)."""

from __future__ import annotations

import time
from types import TracebackType
from typing import Any

import httpx

from gimmethatdata.core.models import FetchAttempt, FetchResult, FetchTier
from gimmethatdata.fetch.tier1_httpx import FetchError


class FlareSolverrFetcher:
    """Talks to a running FlareSolverr instance at `endpoint`."""

    def __init__(
        self,
        endpoint: str,
        *,
        timeout_seconds: float = 60.0,
        proxy: str | None = None,
    ) -> None:
        self._endpoint = endpoint.rstrip("/") + "/v1"
        self._timeout = timeout_seconds
        self._proxy = proxy
        self._client = httpx.AsyncClient(timeout=timeout_seconds)

    async def fetch(self, url: str) -> FetchResult:
        payload: dict[str, Any] = {
            "cmd": "request.get",
            "url": url,
            "maxTimeout": int(self._timeout * 1000),
        }
        if self._proxy:
            payload["proxy"] = {"url": self._proxy}
        started = time.perf_counter()
        try:
            response = await self._client.post(self._endpoint, json=payload)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            elapsed = int((time.perf_counter() - started) * 1000)
            raise FetchError(str(exc), tier=FetchTier.FLARESOLVERR, elapsed_ms=elapsed) from exc

        data = response.json()
        elapsed = int((time.perf_counter() - started) * 1000)
        solution = data.get("solution") or {}
        body_text = solution.get("response", "")
        status = solution.get("status", 0)
        headers_map = {k.lower(): v for k, v in (solution.get("headers") or {}).items()}
        attempt = FetchAttempt(
            tier=FetchTier.FLARESOLVERR, status_code=status, elapsed_ms=elapsed
        )
        return FetchResult(
            url=url,
            final_url=solution.get("url", url),
            status_code=status,
            headers=headers_map,
            body=body_text.encode("utf-8"),
            encoding="utf-8",
            tier=FetchTier.FLARESOLVERR,
            elapsed_ms=elapsed,
            attempts=[attempt],
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> FlareSolverrFetcher:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()
