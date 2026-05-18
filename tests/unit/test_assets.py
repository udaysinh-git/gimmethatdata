"""Tests for parse/assets."""

from __future__ import annotations

from gimmethatdata.core.models import AssetKind
from gimmethatdata.parse.assets import discover_assets, discover_links

BASE = "https://example.com/blog/post-1"


def test_discover_assets_blog(blog_html: str) -> None:
    assets = discover_assets(blog_html, base_url=BASE)
    kinds = {a.kind for a in assets}
    assert AssetKind.IMAGE in kinds
    assert AssetKind.EMBED in kinds
    assert AssetKind.VIDEO in kinds  # /demo.mp4 link
    hero = next(a for a in assets if a.abs_url.endswith("/hero.jpg"))
    assert hero.alt == "A hero image"
    assert hero.width == 800
    embed = next(a for a in assets if a.kind is AssetKind.EMBED)
    assert "youtube.com" in embed.abs_url


def test_discover_assets_doc_video_sources(doc_html: str) -> None:
    assets = discover_assets(doc_html, base_url="https://docs.example.com/api")
    video_urls = {a.abs_url for a in assets if a.kind is AssetKind.VIDEO}
    assert "https://docs.example.com/intro.mp4" in video_urls
    assert "https://docs.example.com/intro.webm" in video_urls


def test_discover_assets_dedupes_duplicate_image(landing_html: str) -> None:
    assets = discover_assets(landing_html, base_url="https://acme.example/")
    logo1_count = sum(1 for a in assets if a.abs_url.endswith("/logo-1.png"))
    assert logo1_count == 1


def test_discover_links_classifies_internal_vs_external(blog_html: str) -> None:
    links = discover_links(blog_html, base_url=BASE)
    wiki = next(link for link in links if "wikipedia.org" in link.abs_url)
    assert wiki.internal is False
    home = next(link for link in links if link.abs_url == "https://example.com/")
    assert home.internal is True
    assert home.anchor == "Home"
