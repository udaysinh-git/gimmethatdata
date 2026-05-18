"""Streamed asset downloader (images, videos, audio) with SHA-256 dedup."""

from __future__ import annotations

import asyncio
import hashlib
import io
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx
from PIL import Image, UnidentifiedImageError

from gimmethatdata.core.models import AssetKind, AssetRef
from gimmethatdata.logging_setup import get_logger
from gimmethatdata.persist.writer import ensure_dir

_log = get_logger(__name__)

_EXT_BY_MIME: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "image/bmp": ".bmp",
    "image/avif": ".avif",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
    "video/x-matroska": ".mkv",
    "audio/mpeg": ".mp3",
    "audio/ogg": ".ogg",
    "audio/wav": ".wav",
    "audio/x-m4a": ".m4a",
    "audio/flac": ".flac",
}


_KIND_TO_DIR: dict[AssetKind, str] = {
    AssetKind.IMAGE: "images",
    AssetKind.VIDEO: "videos",
    AssetKind.AUDIO: "audio",
}


@dataclass
class DownloadOptions:
    """Knobs passed in from the CLI."""

    asset_types: frozenset[AssetKind] = frozenset({AssetKind.IMAGE})
    max_asset_mb: int = 50
    max_total_mb: int = 2048
    max_concurrency: int = 8
    user_agent: str = "gimmethatdata"


def _guess_ext(url: str, content_type: str | None) -> str:
    path = urlparse(url).path
    dot = path.rfind(".")
    if dot >= 0:
        ext = path[dot:].lower().split("?", 1)[0]
        if 1 < len(ext) <= 6 and ext.isascii():
            return ext
    if content_type:
        primary = content_type.split(";", 1)[0].strip().lower()
        if primary in _EXT_BY_MIME:
            return _EXT_BY_MIME[primary]
    return ".bin"


def _image_dims(body: bytes) -> tuple[int | None, int | None]:
    try:
        with Image.open(io.BytesIO(body)) as img:
            return img.width, img.height
    except (UnidentifiedImageError, OSError):
        return None, None


@dataclass
class _Counter:
    """Mutable shared total-bytes counter."""

    total: int = 0


async def _download_one(
    client: httpx.AsyncClient,
    asset: AssetRef,
    out_dir: Path,
    *,
    opts: DownloadOptions,
    sem: asyncio.Semaphore,
    counter: _Counter,
) -> AssetRef:
    kind_dir = _KIND_TO_DIR.get(asset.kind)
    if kind_dir is None:
        return asset
    target_dir = ensure_dir(out_dir / "assets" / kind_dir)
    max_bytes = opts.max_asset_mb * 1024 * 1024
    budget = opts.max_total_mb * 1024 * 1024

    async with sem:
        if counter.total >= budget:
            _log.info("budget_exhausted", url=asset.abs_url)
            return asset
        try:
            response = await client.get(asset.abs_url)
            response.raise_for_status()
            body = response.content
        except httpx.HTTPError as exc:
            _log.warning("asset_download_failed", url=asset.abs_url, error=str(exc))
            return asset
        if len(body) > max_bytes:
            _log.info("asset_skipped_too_large", url=asset.abs_url, bytes=len(body))
            return asset
        if counter.total + len(body) > budget:
            _log.info("asset_skipped_budget", url=asset.abs_url, bytes=len(body))
            return asset
        counter.total += len(body)
        sha = hashlib.sha256(body).hexdigest()
        content_type = response.headers.get("content-type")
        ext = _guess_ext(asset.abs_url, content_type)
        target = target_dir / f"{sha}{ext}"
        if not target.exists():
            target.write_bytes(body)
        local_rel = str(target.relative_to(out_dir)).replace("\\", "/")
        update: dict[str, object] = {
            "sha256": sha,
            "local_path": local_rel,
            "bytes_": len(body),
            "mime": content_type,
        }
        if asset.kind is AssetKind.IMAGE:
            width, height = _image_dims(body)
            if width is not None:
                update["width"] = asset.width or width
            if height is not None:
                update["height"] = asset.height or height
        return asset.model_copy(update=update)


async def download_assets(
    assets: list[AssetRef],
    out_dir: Path,
    *,
    opts: DownloadOptions,
) -> list[AssetRef]:
    """Download every asset whose kind is in `opts.asset_types`."""
    selected_indices = [
        i for i, a in enumerate(assets) if a.kind in opts.asset_types and a.kind in _KIND_TO_DIR
    ]
    if not selected_indices:
        return assets

    sem = asyncio.Semaphore(opts.max_concurrency)
    counter = _Counter()
    async with httpx.AsyncClient(
        timeout=60.0,
        follow_redirects=True,
        headers={"User-Agent": opts.user_agent},
    ) as client:
        tasks = [
            _download_one(
                client, assets[i], out_dir, opts=opts, sem=sem, counter=counter
            )
            for i in selected_indices
        ]
        updated = await asyncio.gather(*tasks)

    new_assets = list(assets)
    for i, ref in zip(selected_indices, updated, strict=False):
        new_assets[i] = ref
    return new_assets
