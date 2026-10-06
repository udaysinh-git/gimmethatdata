"""Universal media sniffer for pages containing embedded or direct media."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gimmethatdata.core.models import (
    AssetKind,
    AssetRef,
    FetchResult,
    LinkRef,
    PageMetadata,
)
from gimmethatdata.fetch.base import Fetcher
from gimmethatdata.media.downloader import (
    DownloadOptions,
    download_assets,
)
from gimmethatdata.media.ytdlp_adapter import (
    YtDlpOptions,
    download_url_via_ytdlp,
    download_via_ytdlp,
    is_supported_embed,
)
from gimmethatdata.parse.assets import discover_assets, discover_links
from gimmethatdata.parse.extractor import extract_main_html, fallback_main_html
from gimmethatdata.parse.metadata import extract_meta
from gimmethatdata.parse.presets import Preset, render


@dataclass
class MediaSniffResult:
    """Media and surrounding metadata discovered from a page."""

    url: str
    media: list[dict[str, Any]] = field(default_factory=list)
    thumbnail: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    content_md: str = ""
    links: list[LinkRef] = field(default_factory=list)


def _asset_to_dict(asset: AssetRef) -> dict[str, Any]:
    """Convert an AssetRef into the public sniffer representation."""
    return {
        "kind": asset.kind.value,
        "url": asset.abs_url,
        "title": asset.title,
        "alt": asset.alt,
        "width": asset.width,
        "height": asset.height,
        "mime": asset.mime,
        "local_path": asset.local_path,
        "bytes": asset.bytes_,
    }


def _find_thumbnail(
    metadata: dict[str, Any],
    assets: list[AssetRef],
) -> str | None:
    """Find the best available thumbnail URL."""
    og = metadata.get("og", {})
    twitter = metadata.get("twitter", {})

    for value in (
        og.get("image"),
        twitter.get("image"),
    ):
        if value:
            return str(value)

    for asset in assets:
        if asset.kind is AssetKind.IMAGE:
            return asset.abs_url

    return None

def _thumbnail_asset(
    thumbnail: str | None,
) -> AssetRef | None:
    """Create an AssetRef for a thumbnail URL."""
    if not thumbnail:
        return None

    return AssetRef(
        kind=AssetKind.IMAGE,
        url=thumbnail,
        abs_url=thumbnail,
    )

def _media_assets(result: MediaSniffResult) -> list[AssetRef]:
    """Convert detected media records into AssetRef objects."""
    assets: list[AssetRef] = []

    for item in result.media:
        kind_value = item.get("kind")

        try:
            kind = AssetKind(kind_value)
        except (TypeError, ValueError):
            continue

        if kind not in {
            AssetKind.VIDEO,
            AssetKind.AUDIO,
        }:
            continue

        media_url = item.get("url")
        if not media_url:
            continue

        assets.append(
            AssetRef(
                kind=kind,
                url=media_url,
                abs_url=media_url,
                title=item.get("title"),
                alt=item.get("alt"),
                width=item.get("width"),
                height=item.get("height"),
                mime=item.get("mime"),
            )
        )

    return assets

async def _download_media(
    result: MediaSniffResult,
    out_dir: Path,
) -> MediaSniffResult:
    """Download detected media and thumbnail into the standard output."""
    media_assets = _media_assets(result)
    downloaded_media: list[AssetRef] = []

    for asset in media_assets:
        if is_supported_embed(result.url):
            platform_asset = asset.model_copy(
                update={
                    "url": result.url,
                    "abs_url": result.url,
                }
            )
            downloaded = await download_via_ytdlp(
                platform_asset,
                out_dir,
                opts=YtDlpOptions(),
            )
        else:
            downloaded = await download_url_via_ytdlp(
                asset.abs_url,
                out_dir,
                opts=YtDlpOptions(),
            )

        if downloaded is not None:
            downloaded_media.append(downloaded)
        else:
            direct = await download_assets(
                [asset],
                out_dir,
                opts=DownloadOptions(
                    asset_types=frozenset({asset.kind}),
                    max_concurrency=1,
                ),
            )
            downloaded_media.extend(direct)

    media = [_asset_to_dict(asset) for asset in downloaded_media]
    thumbnail_result = await _download_thumbnail(result, out_dir)

    return MediaSniffResult(
        url=result.url,
        media=media or result.media,
        thumbnail=thumbnail_result.thumbnail,
        metadata=thumbnail_result.metadata,
        content_md=result.content_md,
        links=result.links,
    )
async def _download_thumbnail(
    result: MediaSniffResult,
    out_dir: Path,
) -> MediaSniffResult:
    """Download the result thumbnail into the standard images directory."""
    thumbnail_asset = _thumbnail_asset(result.thumbnail)

    if thumbnail_asset is None:
        return result

    downloaded = await download_assets(
        [thumbnail_asset],
        out_dir,
        opts=DownloadOptions(
            asset_types=frozenset({AssetKind.IMAGE}),
            max_concurrency=1,
        ),
    )

    thumbnail_asset = downloaded[0]

    return MediaSniffResult(
        url=result.url,
        media=result.media,
        thumbnail=result.thumbnail,
        metadata={
            **result.metadata,
            "thumbnail_local_path": thumbnail_asset.local_path,
            "thumbnail_bytes": thumbnail_asset.bytes_,
        },
    )

def _build_result(
    *,
    url: str,
    fetch_result: FetchResult,
) -> MediaSniffResult:
    """Build a result from fetched HTML."""
    metadata = extract_meta(fetch_result.text)
    assets = discover_assets(
        fetch_result.text,
        base_url=fetch_result.final_url,
    )

    links = discover_links(
        fetch_result.text,
        base_url=fetch_result.final_url,
    )

    media = [
        _asset_to_dict(asset)
        for asset in assets
        if asset.kind
        in {
            AssetKind.VIDEO,
            AssetKind.AUDIO,
            AssetKind.EMBED,
        }
    ]

    main_html = extract_main_html(
        fetch_result.text,
        url=fetch_result.final_url,
    )

    if not main_html or len(main_html.strip()) < 1000:
        main_html = fallback_main_html(fetch_result.text)

    if not main_html:
        title = metadata.get("title") or ""
        description = metadata.get("description") or ""

        main_html = ""
        if title:
            main_html += f"<h1>{title}</h1>"
        if description:
            main_html += f"<p>{description}</p>"

    page_metadata = PageMetadata(
        url=url,
        final_url=fetch_result.final_url,
        status_code=fetch_result.status_code,
        tier=fetch_result.tier,
        elapsed_ms=fetch_result.elapsed_ms,
        fetched_at=fetch_result.fetched_at,
        title=metadata.get("title"),
        description=metadata.get("description"),
    )

    return MediaSniffResult(
        url=url,
        media=media,
        thumbnail=_find_thumbnail(metadata, assets),
        metadata={
            **metadata,
            "final_url": fetch_result.final_url,
            "status_code": fetch_result.status_code,
            "tier": fetch_result.tier,
            "elapsed_ms": fetch_result.elapsed_ms,
            "fetched_at": fetch_result.fetched_at,
            "content_type": fetch_result.headers.get("content-type"),
        },
        content_md=render(Preset.VANILLA, page_metadata, main_html),
        links=links,
    )


async def _run_ytdlp_info(url: str) -> dict[str, Any] | None:
    """Run yt-dlp in metadata-only mode for a page URL."""
    args = [
        "--no-playlist",
        "--no-warnings",
        "--skip-download",
        "--dump-single-json",
        "--quiet",
        "--remote-components",
        "ejs:github",
        url,
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return None

    stdout, _ = await proc.communicate()

    if proc.returncode not in (0, None):
        return None

    try:
        return json.loads(stdout.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return None


def _ytdlp_media(info: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert yt-dlp format information into media records."""
    media_url = info.get("url")

    if media_url:
        video_codec = info.get("vcodec")
        audio_codec = info.get("acodec")

        if video_codec and video_codec != "none":
            kind = AssetKind.VIDEO.value
        elif audio_codec and audio_codec != "none":
            kind = AssetKind.AUDIO.value
        else:
            kind = AssetKind.OTHER.value

        return [
            {
                "kind": kind,
                "url": media_url,
                "title": info.get("title"),
                "alt": None,
                "width": info.get("width"),
                "height": info.get("height"),
                "mime": info.get("mime"),
                "local_path": None,
                "bytes": info.get("filesize") or info.get("filesize_approx"),
            }
        ]

    formats = info.get("formats") or []

    video_formats = [
        fmt for fmt in formats
        if fmt.get("url")
        and fmt.get("vcodec")
        and fmt.get("vcodec") != "none"
    ]

    if not video_formats:
        return []

    best_format = max(
        video_formats,
        key=lambda fmt: (
            fmt.get("height") or 0,
            fmt.get("tbr") or 0,
        ),
    )

    return [
        {
            "kind": AssetKind.VIDEO.value,
            "url": best_format["url"],
            "title": info.get("title"),
            "alt": None,
            "width": best_format.get("width"),
            "height": best_format.get("height"),
            "mime": best_format.get("mime"),
            "local_path": None,
            "bytes": (
                best_format.get("filesize")
                or best_format.get("filesize_approx")
            ),
        }
    ]


async def _sniff_with_ytdlp(url: str) -> MediaSniffResult | None:
    """Try yt-dlp against the original page URL."""
    info = await _run_ytdlp_info(url)
    if info is None:
        return None

    media = _ytdlp_media(info)

    metadata = {
        "title": info.get("title"),
        "description": info.get("description"),
        "uploader": info.get("uploader"),
        "uploader_id": info.get("uploader_id"),
        "channel": info.get("channel"),
        "channel_id": info.get("channel_id"),
        "timestamp": info.get("timestamp"),
        "upload_date": info.get("upload_date"),
        "duration": info.get("duration"),
        "view_count": info.get("view_count"),
        "like_count": info.get("like_count"),
        "webpage_url": info.get("webpage_url") or url,
        "extractor": info.get("extractor"),
        "extractor_key": info.get("extractor_key"),
    }

    metadata = {
        key: value
        for key, value in metadata.items()
        if value is not None
    }

    return MediaSniffResult(
        url=url,
        media=media,
        thumbnail=info.get("thumbnail"),
        metadata=metadata,
        content_md=info.get("description") or "",
    )

def _merge_results(
    html_result: MediaSniffResult,
    ytdlp_result: MediaSniffResult,
) -> MediaSniffResult:
    """Combine webpage metadata with media extracted by yt-dlp."""
    html_media = [
        item for item in html_result.media
        if item.get("kind") != "embed"
    ]

    media = list(html_media)
    existing_urls = {item.get("url") for item in media}

    for item in ytdlp_result.media:
        if item.get("url") not in existing_urls:
            media.append(item)

    metadata = {
        **html_result.metadata,
        **ytdlp_result.metadata,
    }

    return MediaSniffResult(
        url=html_result.url,
        media=media,
        thumbnail=ytdlp_result.thumbnail or html_result.thumbnail,
        metadata=metadata,
        content_md=ytdlp_result.content_md or html_result.content_md,
        links=html_result.links,
    )

async def _sniff_from_html(
    url: str,
    *,
    fetcher: Fetcher | None = None,
) -> MediaSniffResult:
    """Fetch and inspect a page using the existing project fetcher."""
    if fetcher is None:
        raise ValueError("fetcher is required for HTML media sniffing")

    fetch_result = await fetcher.fetch(url)
    return _build_result(
        url=url,
        fetch_result=fetch_result,
    )


async def sniff_media(
    url: str,
    *,
    fetcher: Fetcher | None = None,
    out_dir: Path | None = None,
) -> MediaSniffResult:
    """Discover media, thumbnails, and surrounding metadata.

    yt-dlp is used for platform-aware media extraction. When a fetcher
    is available, the original HTML page is also inspected so that
    surrounding post metadata and directly referenced media are retained.

    When ``out_dir`` is supplied, detected media and the thumbnail are
    downloaded into the standard project asset directories.
    """
    ytdlp_result = await _sniff_with_ytdlp(url)

    if fetcher is not None:
        html_result = await _sniff_from_html(
            url,
            fetcher=fetcher,
        )

        if ytdlp_result is not None:
            result = _merge_results(
                html_result,
                ytdlp_result,
            )
        else:
            result = html_result
    elif ytdlp_result is not None and ytdlp_result.media:
        result = ytdlp_result
    else:
        result = await _sniff_from_html(
            url,
            fetcher=fetcher,
        )

    if out_dir is not None:
        result = await _download_media(
            result,
            out_dir,
        )

    return result
