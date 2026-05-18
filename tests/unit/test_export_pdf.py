"""Tests for export/pdf — HTML builder (no chromium needed)."""

from __future__ import annotations

import json
from pathlib import Path

from gimmethatdata.export.pdf import build_html, discover_pages


def _seed_page(
    page_dir: Path,
    *,
    url: str,
    title: str,
    md_body: str,
    assets: list[dict] | None = None,
    links: list[dict] | None = None,
) -> None:
    page_dir.mkdir(parents=True, exist_ok=True)
    front = (
        "---\n"
        f'url: "{url}"\n'
        f'final_url: "{url}"\n'
        f'title: "{title}"\n'
        'lang: "en"\n'
        'fetched_at: "2026-05-19T03:00:00+00:00"\n'
        "status_code: 200\n"
        'tier: "httpx"\n'
        "---\n\n"
        f"# {title}\n\n{md_body}\n"
    )
    (page_dir / "content.md").write_text(front, encoding="utf-8")
    (page_dir / "metadata.json").write_text(
        json.dumps(
            {
                "url": url,
                "final_url": url,
                "title": title,
                "fetched_at": "2026-05-19T03:00:00+00:00",
                "tier": "httpx",
            }
        ),
        encoding="utf-8",
    )
    (page_dir / "assets.json").write_text(
        json.dumps(assets or []), encoding="utf-8"
    )
    (page_dir / "links.json").write_text(
        json.dumps(links or []), encoding="utf-8"
    )


def test_discover_pages_single_page(tmp_path: Path) -> None:
    _seed_page(tmp_path / "a", url="https://a.example/", title="A", md_body="body")
    pages = discover_pages(tmp_path / "a")
    assert len(pages) == 1
    assert pages[0].metadata["title"] == "A"


def test_discover_pages_recursive(tmp_path: Path) -> None:
    _seed_page(tmp_path / "a", url="https://a.example/1", title="A1", md_body="body")
    _seed_page(tmp_path / "b", url="https://a.example/2", title="A2", md_body="body")
    pages = discover_pages(tmp_path)
    assert len(pages) == 2
    titles = {p.metadata["title"] for p in pages}
    assert titles == {"A1", "A2"}


def test_build_html_includes_cover_toc_and_pages(tmp_path: Path) -> None:
    _seed_page(
        tmp_path / "a",
        url="https://example.com/blog",
        title="Blog",
        md_body="Hello **world** with a [link](https://other.com/).",
        assets=[
            {"kind": "image", "abs_url": "https://example.com/img.png", "local_path": "assets/images/abc.png", "alt": "img"},
            {"kind": "video", "abs_url": "https://youtu.be/abc", "title": "talk"},
        ],
    )
    pages = discover_pages(tmp_path)
    html = build_html(pages, title="Test export", html_root=tmp_path)
    assert "<!doctype html>" in html
    assert "Test export" in html
    assert "Contents" in html
    assert "page-section" in html
    assert "Hello <strong>world</strong>" in html
    # Image rewritten to be reachable from tmp_path root.
    assert "a/assets/images/abc.png" in html
    # Video shows up as a badge link
    assert "badge-video" in html
    assert "https://youtu.be/abc" in html


def test_build_html_strips_frontmatter(tmp_path: Path) -> None:
    _seed_page(tmp_path / "a", url="https://a/", title="A", md_body="body")
    pages = discover_pages(tmp_path)
    html = build_html(pages, title="t", html_root=tmp_path)
    assert "lang: \"en\"" not in html  # frontmatter must not leak into rendered body
