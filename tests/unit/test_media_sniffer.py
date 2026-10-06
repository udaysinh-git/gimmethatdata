"""Tests for the universal media sniffer."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from gimmethatdata.core.models import AssetKind, AssetRef
from gimmethatdata.media.sniffer import (
    MediaSniffResult,
    _download_thumbnail,
    sniff_media,
)


def test_media_sniff_result_defaults() -> None:
    result = MediaSniffResult(url="https://example.com/post")

    assert result.url == "https://example.com/post"
    assert result.media == []
    assert result.thumbnail is None
    assert result.metadata == {}


@pytest.mark.asyncio
async def test_sniff_media_uses_ytdlp_when_available() -> None:
    result = MediaSniffResult(
        url="https://example.com/video",
        media=[
            {
                "url": "https://cdn.example.com/video.mp4",
                "kind": "video",
            }
        ],
        thumbnail="https://cdn.example.com/thumb.jpg",
        metadata={"title": "Example video"},
    )

    with patch(
        "gimmethatdata.media.sniffer._sniff_with_ytdlp",
        new=AsyncMock(return_value=result),
    ):
        actual = await sniff_media("https://example.com/video")

    assert actual.url == "https://example.com/video"
    assert len(actual.media) == 1
    assert actual.thumbnail == "https://cdn.example.com/thumb.jpg"
    assert actual.metadata["title"] == "Example video"


@pytest.mark.asyncio
async def test_sniff_media_falls_back_when_ytdlp_fails() -> None:
    with (
        patch(
            "gimmethatdata.media.sniffer._sniff_with_ytdlp",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "gimmethatdata.media.sniffer._sniff_from_html",
            new=AsyncMock(
                return_value=MediaSniffResult(
                    url="https://example.com/post",
                    media=[
                        {
                            "url": "https://example.com/video.mp4",
                            "kind": "video",
                        }
                    ],
                    thumbnail="https://example.com/thumb.jpg",
                    metadata={"title": "Example post"},
                )
            ),
        ),
    ):
        actual = await sniff_media("https://example.com/post")

    assert len(actual.media) == 1
    assert actual.media[0]["kind"] == "video"
    assert actual.thumbnail == "https://example.com/thumb.jpg"
    assert actual.metadata["title"] == "Example post"

@pytest.mark.asyncio
async def test_sniff_media_merges_html_and_ytdlp_results() -> None:
    from gimmethatdata.media.sniffer import MediaSniffResult

    html_result = MediaSniffResult(
        url="https://example.com/post",
        media=[
            {
                "url": "https://example.com/video.mp4",
                "kind": "video",
            }
        ],
        thumbnail="https://example.com/post.jpg",
        metadata={
            "title": "Example post",
            "description": "A post containing media",
        },
    )

    ytdlp_result = MediaSniffResult(
        url="https://example.com/post",
        media=[
            {
                "url": "https://cdn.example.com/video.mp4",
                "kind": "video",
            }
        ],
        thumbnail="https://cdn.example.com/thumb.jpg",
        metadata={
            "title": "Example video",
            "uploader": "ExampleUser",
        },
    )

    with (
        patch(
            "gimmethatdata.media.sniffer._sniff_with_ytdlp",
            new=AsyncMock(return_value=ytdlp_result),
        ),
        patch(
            "gimmethatdata.media.sniffer._sniff_from_html",
            new=AsyncMock(return_value=html_result),
        ),
    ):
        actual = await sniff_media(
            "https://example.com/post",
            fetcher=AsyncMock(),
        )

    assert len(actual.media) == 2
    assert actual.media[0]["url"] == "https://example.com/video.mp4"
    assert actual.media[1]["url"] == "https://cdn.example.com/video.mp4"
    assert actual.thumbnail == "https://cdn.example.com/thumb.jpg"
    assert actual.metadata["description"] == "A post containing media"
    assert actual.metadata["uploader"] == "ExampleUser"
    assert actual.metadata["title"] == "Example video"

@pytest.mark.asyncio
async def test_download_thumbnail_updates_result(tmp_path: Path) -> None:
    from gimmethatdata.media.sniffer import (
        MediaSniffResult,
    )

    result = MediaSniffResult(
        url="https://example.com/post",
        thumbnail="https://example.com/thumb.jpg",
    )

    downloaded_asset = AssetRef(
        kind=AssetKind.IMAGE,
        url="https://example.com/thumb.jpg",
        abs_url="https://example.com/thumb.jpg",
        local_path="assets/images/thumbnail.jpg",
        bytes=1234,
    )

    with patch(
        "gimmethatdata.media.sniffer.download_assets",
        new=AsyncMock(return_value=[downloaded_asset]),
    ):
        actual = await _download_thumbnail(
            result,
            tmp_path,
        )

    assert actual.thumbnail == "https://example.com/thumb.jpg"
    assert actual.metadata["thumbnail_local_path"] == (
        "assets/images/thumbnail.jpg"
    )
    assert actual.metadata["thumbnail_bytes"] == 1234

@pytest.mark.asyncio
async def test_download_media_downloads_detected_video(
    tmp_path: Path,
) -> None:
    from gimmethatdata.media.sniffer import (
        MediaSniffResult,
        _download_media,
    )

    result = MediaSniffResult(
        url="https://example.com/post",
        media=[
            {
                "kind": "video",
                "url": "https://cdn.example.com/video.mp4",
                "title": "Example video",
            }
        ],
        thumbnail=None,
        metadata={"title": "Example post"},
    )

    downloaded_asset = AssetRef(
        kind=AssetKind.VIDEO,
        url="https://cdn.example.com/video.mp4",
        abs_url="https://cdn.example.com/video.mp4",
        title="Example video",
        local_path="assets/videos/video.mp4",
        bytes=2048,
    )

    with patch(
        "gimmethatdata.media.sniffer.download_url_via_ytdlp",
        new=AsyncMock(return_value=downloaded_asset),
    ):
        actual = await _download_media(
            result,
            tmp_path,
        )

    assert len(actual.media) == 1
    assert actual.media[0]["kind"] == "video"
    assert actual.media[0]["url"] == (
        "https://cdn.example.com/video.mp4"
    )
    assert actual.media[0]["local_path"] == (
        "assets/videos/video.mp4"
    )
    assert actual.media[0]["bytes"] == 2048
    assert actual.metadata["title"] == "Example post"
