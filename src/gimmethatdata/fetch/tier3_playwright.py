"""Tier-3 fetcher: async Playwright + stealth."""

from __future__ import annotations

import time
from types import TracebackType
from typing import TYPE_CHECKING, Any, Literal

from gimmethatdata.core.models import FetchAttempt, FetchResult, FetchTier
from gimmethatdata.fetch.tier1_httpx import FetchError

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Playwright

WaitUntil = Literal["commit", "domcontentloaded", "load", "networkidle"]


class PlaywrightFetcher:
    """Async fetcher backed by headless Chromium with playwright-stealth applied."""

    def __init__(
        self,
        *,
        user_agent: str,
        timeout_seconds: float = 30.0,
        proxy: str | None = None,
        viewport: tuple[int, int] = (1366, 768),
        locale: str = "en-US",
        wait_until: WaitUntil = "domcontentloaded",
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self._user_agent = user_agent
        self._timeout_ms = int(timeout_seconds * 1000)
        self._proxy = proxy
        self._viewport = viewport
        self._locale = locale
        self._wait_until = wait_until
        self._extra_headers = extra_headers or {}
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    async def _ensure_started(self) -> None:
        if self._context is not None:
            return
        from playwright.async_api import async_playwright
        from playwright_stealth import Stealth

        self._pw = await Stealth().use_async(async_playwright()).start()
        launch_kwargs: dict[str, Any] = {"headless": True}
        if self._proxy:
            launch_kwargs["proxy"] = {"server": self._proxy}
        self._browser = await self._pw.chromium.launch(**launch_kwargs)
        self._context = await self._browser.new_context(
            user_agent=self._user_agent,
            viewport={"width": self._viewport[0], "height": self._viewport[1]},
            locale=self._locale,
            extra_http_headers=self._extra_headers or None,
        )
        self._context.set_default_timeout(self._timeout_ms)

    async def fetch(self, url: str) -> FetchResult:
        await self._ensure_started()
        assert self._context is not None
        started = time.perf_counter()
        page = await self._context.new_page()
        try:
            response = await page.goto(url, wait_until=self._wait_until)
            body_text = await page.content()
            final_url = page.url
            status = response.status if response is not None else 0
            headers_map: dict[str, str] = {}
            if response is not None:
                headers_map = {k.lower(): v for k, v in (await response.all_headers()).items()}
        except Exception as exc:
            elapsed = int((time.perf_counter() - started) * 1000)
            await page.close()
            raise FetchError(str(exc), tier=FetchTier.PLAYWRIGHT, elapsed_ms=elapsed) from exc
        else:
            await page.close()
            elapsed = int((time.perf_counter() - started) * 1000)
            attempt = FetchAttempt(
                tier=FetchTier.PLAYWRIGHT, status_code=status, elapsed_ms=elapsed
            )
            return FetchResult(
                url=url,
                final_url=final_url,
                status_code=status,
                headers=headers_map,
                body=body_text.encode("utf-8"),
                encoding="utf-8",
                tier=FetchTier.PLAYWRIGHT,
                elapsed_ms=elapsed,
                attempts=[attempt],
            )

    async def aclose(self) -> None:
        if self._context is not None:
            await self._context.close()
            self._context = None
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._pw is not None:
            await self._pw.stop()
            self._pw = None

    async def __aenter__(self) -> PlaywrightFetcher:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()
