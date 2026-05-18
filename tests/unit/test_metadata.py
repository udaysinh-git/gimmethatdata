"""Tests for parse/metadata."""

from __future__ import annotations

from gimmethatdata.parse.metadata import extract_meta


def test_blog_post_metadata(blog_html: str) -> None:
    meta = extract_meta(blog_html)
    assert meta["title"] == "The Adventure of Scraping"
    assert meta["description"] == "A short post about scraping websites."
    assert meta["lang"] == "en"
    assert meta["canonical"] == "https://example.com/blog/scraping"
    assert meta["og"]["title"] == "The Adventure of Scraping"
    assert meta["og"]["image"] == "https://example.com/og.png"
    assert meta["twitter"]["card"] == "summary_large_image"
    assert any(item.get("@type") == "BlogPosting" for item in meta["jsonld"])
    assert meta["headings"]["h1"] == ["The Adventure of Scraping"]


def test_landing_metadata(landing_html: str) -> None:
    meta = extract_meta(landing_html)
    assert meta["og"]["title"] == "Acme — Build Faster"
    assert meta["og"]["image"] == "/og-banner.png"


def test_doc_metadata(doc_html: str) -> None:
    meta = extract_meta(doc_html)
    assert meta["title"] == "API Reference — Widgets"
    assert "Methods" in meta["headings"]["h2"]
