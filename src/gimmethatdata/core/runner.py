"""Job execution shared by the CLI and the TUI."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gimmethatdata.config import load_settings
from gimmethatdata.core.pipeline import RobotsBlocked, ScrapeOptions, scrape_one
from gimmethatdata.core.url_utils import canonicalize
from gimmethatdata.crawl.crawler import CrawlConfig, CrawlReport, crawl_site
from gimmethatdata.crawl.frontier import ScopeMode, ScopeRule
from gimmethatdata.fetch.factory import FetcherOptions, build_fetcher
from gimmethatdata.fetch.robots import RobotsCache
from gimmethatdata.fetch.tier1_httpx import FetchError
from gimmethatdata.logging_setup import get_logger
from gimmethatdata.persist.index import write_index
from gimmethatdata.persist.ledger import JobStatus, Ledger, make_job_id

_log = get_logger(__name__)


@dataclass
class JobEvent:
    """One observable event during job execution."""

    kind: str  # 'started' | 'page_done' | 'page_failed' | 'finished' | 'crawl_progress'
    url: str | None = None
    output_dir: str | None = None
    tier: str | None = None
    error: str | None = None
    summary: dict[str, int] | None = None
    job_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


Callback = Callable[[JobEvent], Awaitable[None] | None]


@dataclass
class ScrapeJobSpec:
    urls: list[str]
    out: Path
    options: ScrapeOptions
    job_id: str | None = None
    timeout: float = 30.0
    tier: str = "auto"
    proxy: str | None = None
    rate_limit: float = 2.0


@dataclass
class CrawlJobSpec:
    seed_url: str
    out: Path
    depth: int = 2
    max_pages: int = 100
    scope: ScopeMode = ScopeMode.SAME_DOMAIN
    allow: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)
    use_sitemap: bool = True
    options: ScrapeOptions = field(default_factory=ScrapeOptions)
    timeout: float = 30.0
    tier: str = "auto"
    proxy: str | None = None
    rate_limit: float = 1.0


async def _maybe_await(value: Any) -> None:
    if asyncio.iscoroutine(value):
        await value


async def run_scrape_job(
    spec: ScrapeJobSpec,
    *,
    on_event: Callback | None = None,
) -> str:
    """Execute a scrape job. Returns the resolved job_id."""
    settings = load_settings()
    settings.fetch.timeout_seconds = spec.timeout
    fetcher = build_fetcher(
        settings,
        FetcherOptions(tier=spec.tier, proxy=spec.proxy, rate_limit_rps=spec.rate_limit),
    )
    robots = (
        RobotsCache(user_agent=settings.fetch.user_agent)
        if spec.options.respect_robots
        else None
    )
    job_id = spec.job_id or make_job_id()
    ledger = Ledger(spec.out / "_jobs.sqlite")
    await ledger.open()

    async def emit(event: JobEvent) -> None:
        if on_event is None:
            return
        await _maybe_await(on_event(event))

    try:
        await ledger.create_job(job_id, kind="scrape")
        pending = [(u, canonicalize(u)) for u in spec.urls]
        await ledger.upsert_pending(job_id, pending)
        urls_to_run = await ledger.list_pending(job_id)
        await emit(JobEvent(kind="started", job_id=job_id, extra={"total": len(urls_to_run)}))

        try:
            for url in urls_to_run:
                try:
                    result = await scrape_one(
                        fetcher,
                        url,
                        settings=settings,
                        out_root=spec.out,
                        options=spec.options,
                        robots=robots,
                    )
                except RobotsBlocked:
                    await ledger.mark_failed(job_id, url, "robots.txt disallowed")
                    await emit(JobEvent(kind="page_failed", url=url, error="robots.txt disallowed"))
                except FetchError as exc:
                    await ledger.mark_failed(job_id, url, str(exc))
                    await emit(JobEvent(kind="page_failed", url=url, error=str(exc)))
                else:
                    await ledger.mark_done(
                        job_id,
                        url,
                        output_dir=str(result.output_dir),
                        tier=result.metadata.tier.value,
                    )
                    await emit(
                        JobEvent(
                            kind="page_done",
                            url=url,
                            output_dir=str(result.output_dir),
                            tier=result.metadata.tier.value,
                            extra={
                                "assets": len(result.assets),
                                "links": len(result.links),
                            },
                        )
                    )
        except asyncio.CancelledError:
            await ledger.finish_job(job_id, JobStatus.INTERRUPTED)
            raise

        summary = await ledger.job_summary(job_id)
        pages = await ledger.list_done_pages(job_id)
        if pages:
            write_index(spec.out, pages=pages, job_id=job_id)
        status = (
            JobStatus.COMPLETED
            if summary.get("failed", 0) == 0 and summary.get("pending", 0) == 0
            else JobStatus.FAILED
        )
        await ledger.finish_job(job_id, status)
        await emit(JobEvent(kind="finished", summary=summary, job_id=job_id))
        return job_id
    finally:
        await fetcher.aclose()
        await ledger.close()


async def run_resume_job(
    *,
    job_id: str,
    out: Path,
    retry_failed: bool = False,
    options: ScrapeOptions | None = None,
    timeout: float = 30.0,  # noqa: ASYNC109 — per-request HTTP timeout, not a cancel deadline
    tier: str = "auto",
    proxy: str | None = None,
    rate_limit: float = 2.0,
    on_event: Callback | None = None,
) -> str:
    """Resume a previously-started scrape job by id."""
    settings = load_settings()
    settings.fetch.timeout_seconds = timeout
    fetcher = build_fetcher(
        settings, FetcherOptions(tier=tier, proxy=proxy, rate_limit_rps=rate_limit)
    )
    opts = options or ScrapeOptions()
    robots = RobotsCache(user_agent=settings.fetch.user_agent) if opts.respect_robots else None
    ledger = Ledger(out / "_jobs.sqlite")
    await ledger.open()

    async def emit(event: JobEvent) -> None:
        if on_event is None:
            return
        await _maybe_await(on_event(event))

    try:
        urls = await ledger.list_pending(job_id, retry_failed=retry_failed)
        await emit(JobEvent(kind="started", job_id=job_id, extra={"total": len(urls)}))
        if not urls:
            await emit(JobEvent(kind="finished", summary=await ledger.job_summary(job_id), job_id=job_id))
            return job_id
        for url in urls:
            try:
                result = await scrape_one(
                    fetcher,
                    url,
                    settings=settings,
                    out_root=out,
                    options=opts,
                    robots=robots,
                )
            except RobotsBlocked:
                await ledger.mark_failed(job_id, url, "robots.txt disallowed")
                await emit(JobEvent(kind="page_failed", url=url, error="robots.txt disallowed"))
            except FetchError as exc:
                await ledger.mark_failed(job_id, url, str(exc))
                await emit(JobEvent(kind="page_failed", url=url, error=str(exc)))
            else:
                await ledger.mark_done(
                    job_id,
                    url,
                    output_dir=str(result.output_dir),
                    tier=result.metadata.tier.value,
                )
                await emit(
                    JobEvent(
                        kind="page_done",
                        url=url,
                        output_dir=str(result.output_dir),
                        tier=result.metadata.tier.value,
                    )
                )
        summary = await ledger.job_summary(job_id)
        status = (
            JobStatus.COMPLETED
            if summary.get("failed", 0) == 0 and summary.get("pending", 0) == 0
            else JobStatus.FAILED
        )
        await ledger.finish_job(job_id, status)
        await emit(JobEvent(kind="finished", summary=summary, job_id=job_id))
        return job_id
    finally:
        await fetcher.aclose()
        await ledger.close()


async def run_crawl_job(
    spec: CrawlJobSpec,
    *,
    on_event: Callback | None = None,
) -> CrawlReport:
    """Execute a full-site crawl."""
    settings = load_settings()
    settings.fetch.timeout_seconds = spec.timeout
    fetcher = build_fetcher(
        settings, FetcherOptions(tier=spec.tier, proxy=spec.proxy, rate_limit_rps=spec.rate_limit)
    )
    robots = (
        RobotsCache(user_agent=settings.fetch.user_agent)
        if spec.options.respect_robots
        else None
    )
    scope_rule = ScopeRule(
        mode=spec.scope,
        seed=spec.seed_url,
        allow_patterns=spec.allow,
        deny_patterns=spec.deny,
    )
    cfg = CrawlConfig(
        max_depth=spec.depth,
        max_pages=spec.max_pages,
        use_sitemap=spec.use_sitemap,
        scope=scope_rule,
        scrape_options=spec.options,
    )

    async def emit(event: JobEvent) -> None:
        if on_event is None:
            return
        await _maybe_await(on_event(event))

    try:
        await emit(JobEvent(kind="started", url=spec.seed_url))
        report = await crawl_site(
            spec.seed_url,
            fetcher=fetcher,
            settings=settings,
            out_root=spec.out,
            config=cfg,
            robots=robots,
        )
        await emit(
            JobEvent(
                kind="finished",
                summary={
                    "fetched": report.fetched,
                    "failed": report.failed,
                    "skipped": report.skipped,
                },
            )
        )
        return report
    finally:
        await fetcher.aclose()
