"""Full-site crawler driver."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from gimmethatdata.config import Settings
from gimmethatdata.core.pipeline import RobotsBlocked, ScrapeOptions, scrape_one
from gimmethatdata.core.url_utils import canonicalize, domain_of
from gimmethatdata.crawl.frontier import Frontier, FrontierStatus, ScopeRule
from gimmethatdata.crawl.sitemap import discover_sitemap_urls
from gimmethatdata.crawl.sitemap_writer import write_sitemap
from gimmethatdata.crawl.subdomain import discover_subdomain_seeds
from gimmethatdata.fetch.base import Fetcher
from gimmethatdata.fetch.robots import RobotsCache
from gimmethatdata.fetch.tier1_httpx import FetchError
from gimmethatdata.logging_setup import get_logger

_log = get_logger(__name__)


@dataclass
class CrawlConfig:
    """Knobs for `crawl_site`."""

    max_depth: int = 2
    max_pages: int = 100
    use_sitemap: bool = True
    include_subdomains: bool = False
    scope: ScopeRule | None = None
    scrape_options: ScrapeOptions = field(default_factory=ScrapeOptions)


@dataclass
class CrawlReport:
    fetched: int = 0
    failed: int = 0
    skipped: int = 0


async def crawl_site(
    seed_url: str,
    *,
    fetcher: Fetcher,
    settings: Settings,
    out_root: Path,
    config: CrawlConfig,
    robots: RobotsCache | None = None,
) -> CrawlReport:
    """Crawl from `seed_url` within scope, respecting depth + page budget."""
    seed_canonical = canonicalize(seed_url)
    domain = domain_of(seed_canonical)
    site_dir = out_root / domain
    site_dir.mkdir(parents=True, exist_ok=True)
    frontier = Frontier(site_dir / "_site.sqlite")
    await frontier.open()
    scope = config.scope or ScopeRule(seed=seed_canonical)
    report = CrawlReport()

    try:
        await frontier.add([(seed_canonical, 0, None)])
        if config.use_sitemap:
            sitemap_urls = await discover_sitemap_urls(
                seed_canonical, user_agent=settings.fetch.user_agent
            )
            seeded = [
                (u, 0, seed_canonical) for u in sitemap_urls if scope.includes(u)
            ]
            if seeded:
                added = await frontier.add(seeded)
                _log.info("sitemap_seeded", count=added)
        if config.include_subdomains:
            sub_urls = await discover_subdomain_seeds(
                seed_canonical, user_agent=settings.fetch.user_agent
            )
            sub_seeded = [
                (u, 0, seed_canonical) for u in sub_urls if scope.includes(u)
            ]
            if sub_seeded:
                added = await frontier.add(sub_seeded)
                _log.info("subdomains_seeded", count=added)

        while True:
            if report.fetched >= config.max_pages:
                _log.info("crawl_max_pages_reached", max=config.max_pages)
                break
            claim = await frontier.claim_next()
            if claim is None:
                break
            current_url, depth = claim
            if depth > config.max_depth:
                await frontier.mark(current_url, FrontierStatus.SKIPPED)
                report.skipped += 1
                continue
            try:
                result = await scrape_one(
                    fetcher,
                    current_url,
                    settings=settings,
                    out_root=out_root,
                    options=config.scrape_options,
                    robots=robots,
                )
            except RobotsBlocked:
                await frontier.mark(current_url, FrontierStatus.SKIPPED)
                report.skipped += 1
                continue
            except FetchError as exc:
                _log.warning("crawl_fetch_failed", url=current_url, error=str(exc))
                await frontier.mark(current_url, FrontierStatus.FAILED)
                report.failed += 1
                continue

            report.fetched += 1
            await frontier.mark(current_url, FrontierStatus.DONE)

            if depth < config.max_depth:
                new_links = [
                    (link.abs_url, depth + 1, current_url)
                    for link in result.links
                    if scope.includes(link.abs_url)
                ]
                if new_links:
                    await frontier.add(new_links)

        nodes = await frontier.dump_all()
        write_sitemap(site_dir, nodes=nodes, seed=seed_canonical)
        _log.info("sitemap_written", domain=domain, nodes=len(nodes))
        return report
    finally:
        await frontier.close()
