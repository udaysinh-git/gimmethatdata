"""Tests for yt-dlp adapter URL detection."""

from __future__ import annotations

import pytest

from gimmethatdata.media.ytdlp_adapter import is_supported_embed


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
