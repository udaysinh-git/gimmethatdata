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
    format_string = (
        f"best[height<={opts.max_resolution}][ext=mp4]/"
        f"best[height<={opts.max_resolution}]/best"
    )
    args = [
        "--no-playlist",
        "--restrict-filenames",
        "--no-progress",
        "--quiet",
        "--print-json",
        "--remote-components",
        "ejs:github",
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

        # yt-dlp may return a relative filename.
        # Resolve it against the videos directory in that case.
        if not local_path.is_absolute():
            local_path = videos_dir / local_path

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

async def download_url_via_ytdlp(
    url: str,
    out_dir: Path,
    *,
    opts: YtDlpOptions,
) -> AssetRef | None:
    """Download media from any URL supported by yt-dlp."""
    videos_dir = ensure_dir(out_dir / "assets" / "videos")
    output_template = str(videos_dir / "%(id)s.%(ext)s")

    format_string = (
        f"best[height<={opts.max_resolution}][ext=mp4]/"
        f"best[height<={opts.max_resolution}]/best"
    )

    args = [
        "--no-playlist",
        "--restrict-filenames",
        "--no-progress",
        "--quiet",
        "--print-json",
        "--remote-components",
        "ejs:github",
        "-f",
        format_string,
        "-o",
        output_template,
        url,
    ]

    try:
        code, stdout, stderr = await _run_ytdlp(args)
    except FileNotFoundError:
        _log.warning("ytdlp_not_installed", url=url)
        return None

    if code != 0:
        _log.warning(
            "ytdlp_failed",
            url=url,
            stderr=stderr[:500],
        )
        return None

    try:
        info = json.loads(
            stdout.strip().splitlines()[-1]
        )
    except (json.JSONDecodeError, IndexError):
        _log.warning("ytdlp_no_info", url=url)
        return None

    local_filename = (
        info.get("_filename")
        or info.get("filepath")
    )

    if not local_filename:
        return None

    local_path = Path(local_filename)

    if not local_path.is_absolute():
        local_path = videos_dir / local_path

    if not local_path.exists():
        return None

    try:
        local_rel = str(
            local_path.relative_to(out_dir)
        ).replace("\\", "/")
    except ValueError:
        local_rel = str(local_path)

    video_codec = info.get("vcodec")
    audio_codec = info.get("acodec")

    if video_codec and video_codec != "none":
        kind = AssetKind.VIDEO
    elif audio_codec and audio_codec != "none":
        kind = AssetKind.AUDIO
    else:
        kind = AssetKind.OTHER

    return AssetRef(
        kind=kind,
        url=url,
        abs_url=url,
        title=info.get("title"),
        width=info.get("width"),
        height=info.get("height"),
        mime=info.get("mime"),
        local_path=local_rel,
        bytes=local_path.stat().st_size,
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
