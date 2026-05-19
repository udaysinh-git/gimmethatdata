"""Tests for instagram/downloader — fully mocked instaloader."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from gimmethatdata.instagram.client import InstagramClient
from gimmethatdata.instagram.downloader import (
    DownloadOptions,
    _collect_media_urls,
    _post_metadata,
    _render_post_md,
    download_profile,
)


def _fake_post(
    *,
    shortcode: str = "ABC123",
    caption: str = "hello world",
    is_video: bool = False,
    typename: str = "GraphImage",
    url: str = "https://cdn.example/image.jpg",
    likes: int = 10,
    comments: int = 0,
    hashtags: list[str] | None = None,
    mentions: list[str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        shortcode=shortcode,
        caption=caption,
        date_utc=datetime(2026, 5, 19, 10, 0, 0, tzinfo=UTC),
        likes=likes,
        comments=comments,
        is_video=is_video,
        typename=typename,
        url=url,
        owner_username="udaysinh",
        caption_hashtags=hashtags or [],
        caption_mentions=mentions or [],
        tagged_users=[],
        video_view_count=0,
        location=None,
    )


def _fake_profile(*, username: str = "udaysinh", is_private: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        username=username,
        userid=1,
        full_name="Test User",
        biography="bio",
        followers=100,
        followees=50,
        mediacount=2,
        is_private=is_private,
        is_verified=False,
        external_url=None,
        profile_pic_url="https://cdn.example/avatar.jpg",
    )


def test_render_post_md_contains_caption_and_meta() -> None:
    post = _fake_post(
        caption="Big launch today!",
        hashtags=["launch", "ai"],
        mentions=["acme"],
    )
    metadata = _post_metadata(post)
    md = _render_post_md(post, metadata=metadata, asset_count=1)
    assert "Big launch today!" in md
    assert "@udaysinh" in md
    assert "#launch" in md
    assert "@acme" in md
    assert "❤ 10" in md or "10" in md


def test_collect_media_urls_skips_videos() -> None:
    post = _fake_post(is_video=True, typename="GraphVideo", url="https://cdn.example/v.mp4")
    media = _collect_media_urls(post)
    assert len(media) == 1
    assert media[0]["is_video_cover"] is True


def test_collect_media_urls_handles_sidecar() -> None:
    side_a = SimpleNamespace(is_video=False, display_url="https://x/1.jpg")
    side_b = SimpleNamespace(is_video=True, display_url="https://x/2.mp4")
    side_c = SimpleNamespace(is_video=False, display_url="https://x/3.jpg")
    post = SimpleNamespace(
        shortcode="S",
        typename="GraphSidecar",
        is_video=False,
        url="https://x/cover.jpg",
        get_sidecar_nodes=lambda: [side_a, side_b, side_c],
    )
    media = _collect_media_urls(post)  # type: ignore[arg-type]
    urls = [m["abs_url"] for m in media]
    assert urls == ["https://x/1.jpg", "https://x/3.jpg"]


@pytest.mark.parametrize("download_images", [False])
def test_download_profile_writes_layout(tmp_path: Path, download_images: bool) -> None:
    posts = [
        _fake_post(shortcode="AAA", caption="first post"),
        _fake_post(shortcode="BBB", caption="second", is_video=True, typename="GraphVideo"),
    ]
    fake_profile = _fake_profile()
    fake_profile.get_posts = lambda: iter(posts)

    loader = MagicMock()
    client = InstagramClient(loader=loader, logged_in_as=None)

    with patch(
        "gimmethatdata.instagram.downloader.instaloader.Profile.from_username",
        return_value=fake_profile,
    ):
        report = download_profile(
            client,
            "udaysinh",
            out_root=tmp_path,
            options=DownloadOptions(
                fetch_comments=False,
                download_images=download_images,
            ),
        )

    profile_root = tmp_path / "instagram" / "udaysinh"
    assert (profile_root / "profile.json").exists()
    payload = json.loads((profile_root / "profile.json").read_text(encoding="utf-8"))
    assert payload["username"] == "udaysinh"

    post_dir = profile_root / "posts" / "AAA"
    assert (post_dir / "content.md").exists()
    assert (post_dir / "metadata.json").exists()
    assert (post_dir / "assets.json").exists()

    reel_dir = profile_root / "reels" / "BBB"
    assert (reel_dir / "content.md").exists()
    assert report.posts == 1
    assert report.reels == 1


def test_download_profile_aborts_on_private_anonymous(tmp_path: Path) -> None:
    fake_profile = _fake_profile(is_private=True)
    loader = MagicMock()
    client = InstagramClient(loader=loader, logged_in_as=None)
    with patch(
        "gimmethatdata.instagram.downloader.instaloader.Profile.from_username",
        return_value=fake_profile,
    ):
        report = download_profile(client, "private_user", out_root=tmp_path)
    assert report.posts == 0
    assert any("private" in err for err in report.errors)
