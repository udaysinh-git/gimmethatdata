"""Tests for fetch/escalator: challenge detection + tier climbing."""

from __future__ import annotations

import pytest

from gimmethatdata.core.models import FetchResult, FetchTier
from gimmethatdata.fetch.base import Fetcher
from gimmethatdata.fetch.escalator import EscalatingFetcher, is_blocked
from gimmethatdata.fetch.tier1_httpx import FetchError


def _result(*, status: int, body: bytes = b"<html><body>ok</body></html>", headers: dict[str, str] | None = None, tier: FetchTier = FetchTier.HTTPX) -> FetchResult:
    return FetchResult(
        url="https://example.com/",
        final_url="https://example.com/",
        status_code=status,
        headers=headers or {},
        body=body,
        encoding="utf-8",
        tier=tier,
        elapsed_ms=10,
    )


def test_is_blocked_on_403_cloudflare() -> None:
    assert is_blocked(_result(status=403, headers={"server": "cloudflare"}))


def test_is_blocked_on_503_with_cf_mitigated() -> None:
    assert is_blocked(_result(status=503, headers={"cf-mitigated": "challenge"}))


def test_is_blocked_on_just_a_moment_body() -> None:
    body = b"<html><body>Just a moment...</body></html>"
    assert is_blocked(_result(status=200, body=body, headers={"cf-ray": "abc"}))


def test_not_blocked_on_normal_200() -> None:
    assert not is_blocked(_result(status=200, body=b"<html>hi</html>"))


class _StubFetcher:
    """Deterministic Fetcher stub returning queued results or raising."""

    def __init__(self, results: list[FetchResult | Exception]) -> None:
        self._results = list(results)
        self.calls = 0

    async def fetch(self, url: str) -> FetchResult:
        self.calls += 1
        item = self._results.pop(0)
        if isinstance(item, Exception):
            raise item
        item.url = url
        item.final_url = url
        return item

    async def aclose(self) -> None:
        return None


def _stub(results: list[FetchResult | Exception]) -> Fetcher:
    return _StubFetcher(results)  # type: ignore[return-value]


@pytest.mark.asyncio
async def test_escalator_returns_tier1_when_unblocked() -> None:
    t1 = _StubFetcher([_result(status=200, tier=FetchTier.HTTPX)])
    t2 = _StubFetcher([_result(status=200, tier=FetchTier.CURL_CFFI)])
    esc = EscalatingFetcher([t1, t2])  # type: ignore[list-item]
    result = await esc.fetch("https://example.com/")
    assert result.tier is FetchTier.HTTPX
    assert t1.calls == 1
    assert t2.calls == 0


@pytest.mark.asyncio
async def test_escalator_climbs_past_cf_challenge() -> None:
    blocked = _result(
        status=403, headers={"server": "cloudflare", "cf-mitigated": "challenge"}, tier=FetchTier.HTTPX
    )
    success = _result(status=200, tier=FetchTier.CURL_CFFI)
    t1 = _StubFetcher([blocked])
    t2 = _StubFetcher([success])
    esc = EscalatingFetcher([t1, t2])  # type: ignore[list-item]
    result = await esc.fetch("https://example.com/")
    assert result.tier is FetchTier.CURL_CFFI


@pytest.mark.asyncio
async def test_escalator_skips_tier_on_fetch_error() -> None:
    err = FetchError("boom", tier=FetchTier.HTTPX, elapsed_ms=5)
    success = _result(status=200, tier=FetchTier.CURL_CFFI)
    t1 = _StubFetcher([err])
    t2 = _StubFetcher([success])
    esc = EscalatingFetcher([t1, t2])  # type: ignore[list-item]
    result = await esc.fetch("https://example.com/")
    assert result.tier is FetchTier.CURL_CFFI
