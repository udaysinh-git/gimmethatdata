"""Tests for yt-dlp adapter URL detection."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from gimmethatdata.core.models import AssetKind, AssetRef
from gimmethatdata.media.ytdlp_adapter import (
    YtDlpOptions,
    download_url_via_ytdlp,
    download_via_ytdlp,
    is_supported_embed,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/embed/abc123",
        "https://youtu.be/abc123",
        "https://player.vimeo.com/video/12345",
        "https://www.dailymotion.com/embed/video/x123",
        "https://www.twitch.tv/videos/12345",
    ],
)
def test_supported_embeds(url: str) -> None:
    assert is_supported_embed(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/embed/video",
        "https://cdn.example.com/video.mp4",
        "https://twitter.com/status/123",
    ],
)
def test_unsupported_embeds(url: str) -> None:
    assert not is_supported_embed(url)


@pytest.mark.asyncio
async def test_download_url_via_ytdlp_returns_asset(
    tmp_path: Path,
) -> None:
    videos_dir = tmp_path / "assets" / "videos"
    videos_dir.mkdir(parents=True)

    media_file = videos_dir / "example.mp4"
    media_file.write_bytes(b"fake video data")

    info = {
        "_filename": str(media_file),
        "title": "Example video",
        "width": 1280,
        "height": 720,
        "vcodec": "h264",
        "acodec": "aac",
        "mime": "video/mp4",
    }

    with patch(
        "gimmethatdata.media.ytdlp_adapter._run_ytdlp",
        new=AsyncMock(
            return_value=(
                0,
                json.dumps(info),
                "",
            )
        ),
    ) as mock_run:
        result = await download_url_via_ytdlp(
            "https://example.com/video",
            tmp_path,
            opts=YtDlpOptions(),
        )

    assert result is not None
    assert result.kind.value == "video"
    assert result.title == "Example video"
    assert result.local_path == "assets/videos/example.mp4"
    assert result.bytes_ == len(b"fake video data")

    args = mock_run.await_args.args[0]

    assert "-f" in args
    format_index = args.index("-f")
    assert args[format_index + 1] == (
        "best[height<=720][ext=mp4]/"
        "best[height<=720]/best"
    )

@pytest.mark.asyncio
async def test_download_via_ytdlp_resolves_relative_filename(
    tmp_path: Path,
) -> None:
    videos_dir = tmp_path / "assets" / "videos"
    videos_dir.mkdir(parents=True)

    media_file = videos_dir / "example.mp4"
    media_file.write_bytes(b"relative video data")

    info = {
        "_filename": "example.mp4",
        "title": "Relative example",
        "width": 1280,
        "height": 720,
        "vcodec": "h264",
        "acodec": "aac",
        "mime": "video/mp4",
    }

    with patch(
        "gimmethatdata.media.ytdlp_adapter._run_ytdlp",
        new=AsyncMock(
            return_value=(
                0,
                json.dumps(info),
                "",
            )
        ),
    ):
        result = await download_via_ytdlp(
            AssetRef(
                kind=AssetKind.VIDEO,
                url="https://example.com/video",
                abs_url="https://www.youtube.com/watch?v=example",
            ),
            tmp_path,
            opts=YtDlpOptions(),
        )

    assert result.local_path == "assets/videos/example.mp4"
    assert result.bytes_ == len(b"relative video data")
