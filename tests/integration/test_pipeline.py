"""End-to-end pipeline integration test using respx."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from gimmethatdata.config import load_settings
from gimmethatdata.core.models import AssetKind
from gimmethatdata.core.pipeline import ScrapeOptions, scrape_one
from gimmethatdata.fetch.tier1_httpx import HttpxFetcher


@pytest.mark.asyncio
@respx.mock
async def test_pipeline_writes_full_layout(tmp_path: Path, blog_html: str) -> None:
    url = "https://example.com/blog/post-1"
    respx.get(url).mock(
        return_value=httpx.Response(
            200,
            text=blog_html,
            headers={"content-type": "text/html; charset=utf-8", "server": "nginx"},
        )
    )

    settings = load_settings()
    async with HttpxFetcher(user_agent=settings.fetch.user_agent) as fetcher:
        result = await scrape_one(
            fetcher,
            url,
            settings=settings,
            out_root=tmp_path,
            options=ScrapeOptions(keep_html=True, respect_robots=False),
        )

    assert (result.output_dir / "content.md").exists()
    assert (result.output_dir / "metadata.json").exists()
    assert (result.output_dir / "assets.json").exists()
    assert (result.output_dir / "links.json").exists()
    assert (result.output_dir / "raw.html").exists()

    content = (result.output_dir / "content.md").read_text(encoding="utf-8")
    assert "The Adventure of Scraping" in content
    assert content.startswith("---")

    meta = json.loads((result.output_dir / "metadata.json").read_text(encoding="utf-8"))
    assert meta["title"] == "The Adventure of Scraping"
    assert meta["tier"] == "httpx"
    assert meta["status_code"] == 200

    assets = json.loads((result.output_dir / "assets.json").read_text(encoding="utf-8"))
    assert any(a["kind"] == "image" for a in assets)
    assert any(a["kind"] == "embed" for a in assets)


@pytest.mark.asyncio
@respx.mock
async def test_pipeline_downloads_images(tmp_path: Path, landing_html: str) -> None:
    url = "https://acme.example/"
    respx.get(url).mock(
        return_value=httpx.Response(200, text=landing_html, headers={"content-type": "text/html"})
    )
    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    respx.get("https://acme.example/logo-1.png").mock(
        return_value=httpx.Response(200, content=fake_png, headers={"content-type": "image/png"})
    )
    respx.get("https://acme.example/logo-2.png").mock(
        return_value=httpx.Response(200, content=fake_png + b"x", headers={"content-type": "image/png"})
    )
    respx.get("https://cdn.example.com/hero.webp").mock(
        return_value=httpx.Response(200, content=b"WEBP" * 32, headers={"content-type": "image/webp"})
    )

    settings = load_settings()
    async with HttpxFetcher(user_agent=settings.fetch.user_agent) as fetcher:
        result = await scrape_one(
            fetcher,
            url,
            settings=settings,
            out_root=tmp_path,
            options=ScrapeOptions(
                asset_types=frozenset({AssetKind.IMAGE}),
                respect_robots=False,
            ),
        )

    images_dir = result.output_dir / "assets" / "images"
    assert images_dir.exists()
    files = list(images_dir.glob("*"))
    assert len(files) >= 2  # logo-1 + logo-2 + hero (logo-1 duplicated dedupes to 1)
    downloaded = [a for a in result.assets if a.local_path]
    assert downloaded, "expected at least one image to have local_path set"
