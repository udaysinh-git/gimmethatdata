"""Scrape pipeline: fetch -> parse -> extract -> persist."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from gimmethatdata.config import Settings
from gimmethatdata.core.models import AssetKind, FetchResult, PageMetadata, PageResult
from gimmethatdata.core.url_utils import canonicalize, derive_output_dir
from gimmethatdata.fetch.base import Fetcher
from gimmethatdata.fetch.robots import RobotsCache
from gimmethatdata.logging_setup import get_logger
from gimmethatdata.media.downloader import DownloadOptions, download_assets
from gimmethatdata.media.ytdlp_adapter import YtDlpOptions, download_embeds
from gimmethatdata.parse.assets import discover_assets, discover_links
from gimmethatdata.parse.extractor import extract_main_html, fallback_main_html
from gimmethatdata.parse.metadata import extract_meta
from gimmethatdata.parse.ocr import append_ocr_section, ocr_local_assets
from gimmethatdata.parse.pdf_extract import is_pdf_response, parse_pdf_bytes, pdf_to_markdown
from gimmethatdata.parse.plugins import Extractor, select_extractor
from gimmethatdata.parse.presets import Preset, render
from gimmethatdata.persist.writer import write_page

_log = get_logger(__name__)


class RobotsBlocked(Exception):
    """Raised when robots.txt disallows the requested URL."""


def _build_pdf_page(
    *,
    canonical_url: str,
    fetch_result: FetchResult,
    base_url: str,
) -> tuple[PageMetadata, str, list, list]:  # type: ignore[type-arg]
    """Build metadata + body for a PDF response."""
    from gimmethatdata.parse.markdown import html_to_markdown as _md_passthrough  # noqa: F401

    doc = parse_pdf_bytes(fetch_result.body)
    headers_keep = {
        k: v
        for k, v in fetch_result.headers.items()
        if k in {"content-type", "content-length", "server", "etag", "last-modified"}
    }
    meta_extra: dict[str, str] = dict(doc.meta) if doc else {}
    metadata = PageMetadata(
        url=canonical_url,
        final_url=base_url,
        title=(doc.title if doc and doc.title else "PDF document"),
        description=meta_extra.get("subject"),
        lang=None,
        canonical=None,
        meta=meta_extra,
        http_headers=headers_keep,
        status_code=fetch_result.status_code,
        tier=fetch_result.tier,
        elapsed_ms=fetch_result.elapsed_ms,
        fetched_at=fetch_result.fetched_at,
    )
    body = (
        "<pre>" + (pdf_to_markdown(doc).replace("&", "&amp;").replace("<", "&lt;")) + "</pre>"
        if doc
        else "<p><em>PDF could not be parsed.</em></p>"
    )
    return metadata, body, [], []


@dataclass
class ScrapeOptions:
    """Per-scrape user options."""

    asset_types: frozenset[AssetKind] = field(default_factory=lambda: frozenset())
    max_asset_mb: int = 50
    max_total_mb: int = 2048
    download_concurrency: int = 8
    keep_html: bool = False
    respect_robots: bool = True
    download_video_embeds: bool = False
    preset: Preset = Preset.VANILLA
    enable_ocr: bool = False
    extractors: list[Extractor] = field(default_factory=list)


async def scrape_one(
    fetcher: Fetcher,
    url: str,
    *,
    settings: Settings,
    out_root: Path,
    options: ScrapeOptions | None = None,
    robots: RobotsCache | None = None,
) -> PageResult:
    """Scrape a single URL through the full pipeline."""
    opts = options or ScrapeOptions()
    canonical_url = canonicalize(url)

    if opts.respect_robots and robots is not None and not await robots.allowed(canonical_url):
        _log.warning("robots_disallowed", url=canonical_url)
        raise RobotsBlocked(canonical_url)

    _log.info("fetch_start", url=canonical_url)
    fetch_result: FetchResult = await fetcher.fetch(canonical_url)
    _log.info(
        "fetch_done",
        url=canonical_url,
        status=fetch_result.status_code,
        tier=fetch_result.tier.value,
        ms=fetch_result.elapsed_ms,
    )

    base_url = fetch_result.final_url
    content_type = fetch_result.headers.get("content-type")
    is_pdf = is_pdf_response(content_type=content_type, body=fetch_result.body)

    if is_pdf:
        page_metadata, main_html, assets, links = _build_pdf_page(
            canonical_url=canonical_url,
            fetch_result=fetch_result,
            base_url=base_url,
        )
    else:
        html_text = fetch_result.text
        meta_dict = extract_meta(html_text)
        page_metadata = PageMetadata(
            url=canonical_url,
            final_url=base_url,
            status_code=fetch_result.status_code,
            tier=fetch_result.tier,
            elapsed_ms=fetch_result.elapsed_ms,
            fetched_at=fetch_result.fetched_at,
            http_headers={
                k: v
                for k, v in fetch_result.headers.items()
                if k in {"content-type", "content-length", "server", "cf-ray", "x-cache"}
            },
            **meta_dict,
        )

        extractor = select_extractor(opts.extractors, canonical_url) if opts.extractors else None
        if extractor is not None:
            doc = extractor.extract(html_text, url=canonical_url)
            if doc is not None:
                main_html = doc.main_html
                if doc.title and not page_metadata.title:
                    page_metadata.title = doc.title
                if doc.extra_meta:
                    page_metadata.meta.update(doc.extra_meta)
                _log.info("extractor_used", name=extractor.name, url=canonical_url)
            else:
                main_html = extract_main_html(html_text, url=base_url) or fallback_main_html(html_text)
        else:
            main_html = extract_main_html(html_text, url=base_url) or fallback_main_html(html_text)
        assets = discover_assets(html_text, base_url=base_url)
        links = discover_links(html_text, base_url=base_url)

    out_dir = derive_output_dir(out_root, base_url)

    if opts.asset_types:
        assets = await download_assets(
            assets,
            out_dir,
            opts=DownloadOptions(
                asset_types=opts.asset_types,
                max_asset_mb=opts.max_asset_mb,
                max_total_mb=opts.max_total_mb,
                max_concurrency=opts.download_concurrency,
                user_agent=settings.fetch.user_agent,
            ),
        )
    if opts.download_video_embeds:
        assets = await download_embeds(
            assets, out_dir, opts=YtDlpOptions()
        )

    content_md = render(opts.preset, page_metadata, main_html)
    if opts.enable_ocr:
        ocr_text = ocr_local_assets(assets, out_dir)
        content_md = append_ocr_section(content_md, ocr_text)
    write_page(
        out_dir,
        content_md=content_md,
        metadata=page_metadata,
        assets=assets,
        links=links,
        raw_html=fetch_result.body if opts.keep_html else None,
    )

    _log.info(
        "page_persisted",
        url=canonical_url,
        out=str(out_dir),
        assets=len(assets),
        links=len(links),
    )
    return PageResult(
        url=canonical_url,
        output_dir=out_dir,
        metadata=page_metadata,
        content_md=content_md,
        assets=assets,
        links=links,
        raw_html_path=(out_dir / "raw.html") if opts.keep_html else None,
    )
