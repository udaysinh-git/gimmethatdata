"""yt-dlp adapter for embedded video/audio platforms."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from gimmethatdata.core.models import AssetKind, AssetRef
from gimmethatdata.logging_setup import get_logger
from gimmethatdata.persist.writer import ensure_dir

_log = get_logger(__name__)

_EMBED_PATTERNS: tuple[str, ...] = (
    "youtube.com/", "youtu.be/", "youtube.com/embed/",
    "vimeo.com/", "player.vimeo.com/",
    "dailymotion.com/", "twitch.tv/",
)


@dataclass
class YtDlpOptions:
    """Knobs for yt-dlp invocation."""

    format: str = "bestvideo*+bestaudio/best"
    max_resolution: int = 720


def is_supported_embed(url: str) -> bool:
    return any(pattern in url for pattern in _EMBED_PATTERNS)


async def _run_ytdlp(args: list[str]) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        "yt-dlp", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode or 0, stdout.decode("utf-8", errors="replace"), stderr.decode("utf-8", errors="replace")


async def download_via_ytdlp(
    asset: AssetRef,
    out_dir: Path,
    *,
    opts: YtDlpOptions,
) -> AssetRef:
    """Download a single embed asset using yt-dlp."""
    if not is_supported_embed(asset.abs_url):
        return asset
    videos_dir = ensure_dir(out_dir / "assets" / "videos")
    output_template = str(videos_dir / "%(id)s.%(ext)s")
    format_string = f"{opts.format}[height<={opts.max_resolution}]"
    args = [
        "--no-playlist",
        "--restrict-filenames",
        "--no-progress",
        "--quiet",
        "--print-json",
        "-f", format_string,
        "-o", output_template,
        asset.abs_url,
    ]
    try:
        code, stdout, stderr = await _run_ytdlp(args)
    except FileNotFoundError:
        _log.warning("ytdlp_not_installed", url=asset.abs_url)
        return asset
    if code != 0:
        _log.warning("ytdlp_failed", url=asset.abs_url, stderr=stderr[:500])
        return asset
    try:
        info = json.loads(stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        _log.warning("ytdlp_no_info", url=asset.abs_url)
        return asset

    local_filename = info.get("_filename") or info.get("filepath")
    local_rel: str | None = None
    bytes_: int | None = None
    if local_filename:
        local_path = Path(local_filename)
        if local_path.exists():
            local_rel = str(local_path.relative_to(out_dir)).replace("\\", "/")
            bytes_ = local_path.stat().st_size

    return asset.model_copy(
        update={
            "kind": AssetKind.VIDEO,
            "local_path": local_rel,
            "bytes_": bytes_,
            "title": info.get("title") or asset.title,
        }
    )


async def download_embeds(
    assets: list[AssetRef],
    out_dir: Path,
    *,
    opts: YtDlpOptions,
) -> list[AssetRef]:
    """Download every embed asset whose host is supported."""
    indices = [
        i for i, a in enumerate(assets)
        if a.kind is AssetKind.EMBED and is_supported_embed(a.abs_url)
    ]
    if not indices:
        return assets

    updated = await asyncio.gather(
        *(download_via_ytdlp(assets[i], out_dir, opts=opts) for i in indices)
    )
    new_assets = list(assets)
    for i, ref in zip(indices, updated, strict=False):
        new_assets[i] = ref
    return new_assets
