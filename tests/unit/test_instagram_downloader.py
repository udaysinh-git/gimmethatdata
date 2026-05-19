"""Tests for instagram/downloader — fully mocked instagrapi."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from gimmethatdata.instagram.client import InstagramClient
from gimmethatdata.instagram.downloader import (
    DownloadOptions,
    _collect_media_refs,
    _is_reel,
    _media_metadata,
    _render_media_md,
    _serialize_user,
    download_profile,
)


def _fake_user(*, username: str = "udaysinh", is_private: bool = False, pk: int = 42) -> SimpleNamespace:
    return SimpleNamespace(
        username=username,
        pk=pk,
        full_name="Test User",
        biography="bio",
        follower_count=100,
        following_count=50,
        media_count=2,
        is_private=is_private,
        is_verified=False,
        external_url=None,
        profile_pic_url="https://cdn.example/avatar.jpg",
    )


def _fake_media(
    *,
    code: str = "ABC123",
    pk: int = 1,
    media_type: int = 1,  # 1=photo, 2=video, 8=carousel
    product_type: str = "feed",
    caption: str = "hello world",
    likes: int = 10,
    comments_count: int = 0,
    thumbnail_url: str = "https://cdn.example/image.jpg",
    resources: list | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        code=code,
        pk=pk,
        id=f"{pk}_999",
        media_type=media_type,
        product_type=product_type,
        caption_text=caption,
        taken_at=datetime(2026, 5, 19, 10, 0, 0, tzinfo=UTC),
        like_count=likes,
        comment_count=comments_count,
        view_count=0,
        play_count=0,
        location=None,
        thumbnail_url=thumbnail_url,
        resources=resources or [],
        user=SimpleNamespace(username="udaysinh"),
    )


def test_serialize_user_returns_flat_dict() -> None:
    user = _fake_user()
    payload = _serialize_user(user)
    assert payload["username"] == "udaysinh"
    assert payload["followers"] == 100
    assert payload["is_private"] is False


def test_is_reel_classification() -> None:
    assert _is_reel(_fake_media(media_type=2, product_type="clips"))
    assert _is_reel(_fake_media(media_type=2, product_type="feed_video"))
    assert not _is_reel(_fake_media(media_type=1, product_type="feed"))
    assert not _is_reel(_fake_media(media_type=8, product_type="feed"))


def test_collect_media_refs_carousel() -> None:
    r1 = SimpleNamespace(media_type=1, thumbnail_url="https://x/1.jpg")
    r2 = SimpleNamespace(media_type=2, thumbnail_url="https://x/2.jpg")  # video slide → cover only
    r3 = SimpleNamespace(media_type=1, thumbnail_url="https://x/3.jpg")
    media = _fake_media(media_type=8, resources=[r1, r2, r3])
    refs = _collect_media_refs(media)
    urls = [r["abs_url"] for r in refs]
    assert urls == ["https://x/1.jpg", "https://x/2.jpg", "https://x/3.jpg"]
    assert refs[1].get("is_video_cover") is True


def test_collect_media_refs_video() -> None:
    media = _fake_media(media_type=2, product_type="clips", thumbnail_url="https://x/cover.jpg")
    refs = _collect_media_refs(media)
    assert len(refs) == 1
    assert refs[0]["is_video_cover"] is True


def test_render_media_md_has_caption_and_hashtags() -> None:
    media = _fake_media(caption="Big launch! #launch @acme")
    metadata = _media_metadata(media)
    md = _render_media_md(media, metadata=metadata, asset_count=1)
    assert "Big launch!" in md
    assert "@udaysinh" in md
    assert "#launch" in md
    assert "@acme" in md


@pytest.mark.parametrize("download_images", [False])
def test_download_profile_writes_layout(tmp_path: Path, download_images: bool) -> None:
    user = _fake_user()
    medias = [
        _fake_media(code="AAA", caption="first post", media_type=1, product_type="feed"),
        _fake_media(
            code="BBB",
            caption="reel",
            media_type=2,
            product_type="clips",
            thumbnail_url="https://x/reel-cover.jpg",
        ),
    ]
    ig = MagicMock()
    ig.user_info_by_username.return_value = user
    ig.user_medias.return_value = medias

    client = InstagramClient(client=ig, logged_in_as=None)

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

    assert (profile_root / "posts" / "AAA" / "content.md").exists()
    assert (profile_root / "reels" / "BBB" / "content.md").exists()
    assert report.posts == 1
    assert report.reels == 1


def test_download_profile_aborts_on_private_anonymous(tmp_path: Path) -> None:
    user = _fake_user(is_private=True)
    ig = MagicMock()
    ig.user_info_by_username.return_value = user
    client = InstagramClient(client=ig, logged_in_as=None)
    report = download_profile(client, "private_user", out_root=tmp_path)
    assert report.posts == 0
    assert any("private" in err for err in report.errors)
