"""Build an EscalatingFetcher (or a single tier) from runtime options."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from gimmethatdata.fetch.auth import AuthConfig
from gimmethatdata.fetch.base import Fetcher
from gimmethatdata.fetch.escalator import EscalatingFetcher
from gimmethatdata.fetch.http_cache import HttpCache
from gimmethatdata.fetch.rate_limit import DomainRateLimiter
from gimmethatdata.fetch.tier1_httpx import HttpxFetcher

if TYPE_CHECKING:
    from gimmethatdata.config import Settings


@dataclass
class FetcherOptions:
    """Runtime knobs for the fetcher stack."""

    tier: str = "auto"  # auto | 1 | 2 | 3 | 4
    proxy: str | None = None
    rate_limit_rps: float = 2.0
    auth: AuthConfig = field(default_factory=AuthConfig)
    cache_dir: Path | None = None


def _make_httpx(settings: Settings, options: FetcherOptions) -> HttpxFetcher:
    cache = HttpCache(options.cache_dir) if options.cache_dir is not None else None
    return HttpxFetcher(
        user_agent=settings.fetch.user_agent,
        timeout_seconds=settings.fetch.timeout_seconds,
        follow_redirects=settings.fetch.follow_redirects,
        verify_tls=settings.fetch.verify_tls,
        proxy=options.proxy,
        auth=options.auth,
        cache=cache,
    )


def _make_curl(settings: Settings, options: FetcherOptions) -> Fetcher:
    from gimmethatdata.fetch.tier2_curl_cffi import CurlCffiFetcher

    return CurlCffiFetcher(
        user_agent=settings.fetch.user_agent,
        timeout_seconds=settings.fetch.timeout_seconds,
        proxy=options.proxy,
        extra_headers=options.auth.header_overrides(),
    )


def _make_playwright(settings: Settings, options: FetcherOptions) -> Fetcher:
    from gimmethatdata.fetch.tier3_playwright import PlaywrightFetcher

    return PlaywrightFetcher(
        user_agent=settings.fetch.user_agent,
        timeout_seconds=settings.fetch.timeout_seconds,
        proxy=options.proxy,
        extra_headers=options.auth.header_overrides(),
    )


def _make_flaresolverr(_: Settings, options: FetcherOptions) -> Fetcher | None:
    endpoint = os.environ.get("FLARESOLVERR_URL")
    if not endpoint:
        return None
    from gimmethatdata.fetch.tier4_flaresolverr import FlareSolverrFetcher

    return FlareSolverrFetcher(endpoint, proxy=options.proxy)


def build_fetcher(settings: Settings, options: FetcherOptions) -> Fetcher:
    """Build a single-tier or escalating fetcher based on options."""
    rate = DomainRateLimiter(requests_per_second=options.rate_limit_rps)

    if options.tier == "1":
        return _make_httpx(settings, options)
    if options.tier == "2":
        return _make_curl(settings, options)
    if options.tier == "3":
        return _make_playwright(settings, options)
    if options.tier == "4":
        fs = _make_flaresolverr(settings, options)
        if fs is None:
            raise RuntimeError("FlareSolverr requested but FLARESOLVERR_URL is not set")
        return fs

    tiers: list[Fetcher] = [
        _make_httpx(settings, options),
        _make_curl(settings, options),
        _make_playwright(settings, options),
    ]
    fs = _make_flaresolverr(settings, options)
    if fs is not None:
        tiers.append(fs)
    return EscalatingFetcher(tiers, rate_limiter=rate)
