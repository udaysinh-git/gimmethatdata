"""Tests for crawl/sitemap_writer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gimmethatdata.crawl.frontier import Frontier, FrontierStatus
from gimmethatdata.crawl.sitemap_writer import write_sitemap, write_sitemap_from_frontier


def test_write_sitemap_renders_tree_and_json(tmp_path: Path) -> None:
    domain_dir = tmp_path / "example.com"
    nodes = [
        {
            "canonical_url": "https://example.com/",
            "depth": 0,
            "status": "done",
            "discovered_at": "2026-05-19T03:10:00+00:00",
            "parent_url": None,
        },
        {
            "canonical_url": "https://example.com/blog",
            "depth": 1,
            "status": "done",
            "discovered_at": "2026-05-19T03:10:01+00:00",
            "parent_url": "https://example.com/",
        },
        {
            "canonical_url": "https://example.com/blog/post-1",
            "depth": 2,
            "status": "failed",
            "discovered_at": "2026-05-19T03:10:02+00:00",
            "parent_url": "https://example.com/blog",
        },
        {
            "canonical_url": "https://example.com/about",
            "depth": 1,
            "status": "pending",
            "discovered_at": "2026-05-19T03:10:03+00:00",
            "parent_url": "https://example.com/",
        },
    ]
    json_path, md_path = write_sitemap(
        domain_dir, nodes=nodes, seed="https://example.com/"
    )
    assert json_path.exists()
    assert md_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["total"] == 4
    assert payload["counts"] == {"done": 2, "failed": 1, "pending": 1}
    assert payload["seed"] == "https://example.com/"
    assert len(payload["edges"]) == 3

    md = md_path.read_text(encoding="utf-8")
    assert "Sitemap — example.com" in md
    assert "https://example.com/blog" in md
    assert "https://example.com/blog/post-1" in md
    # The seed root should appear before its children — tree indentation present
    assert "  - " in md


def test_write_sitemap_lists_orphans(tmp_path: Path) -> None:
    domain_dir = tmp_path / "example.com"
    nodes = [
        {
            "canonical_url": "https://example.com/orphan",
            "depth": 0,
            "status": "done",
            "discovered_at": "2026-05-19T03:10:00+00:00",
            "parent_url": "https://NOT-IN-FRONTIER.example/",
        },
    ]
    _json, md_path = write_sitemap(domain_dir, nodes=nodes, seed="https://example.com/")
    md = md_path.read_text(encoding="utf-8")
    assert "Orphans" in md
    assert "https://example.com/orphan" in md


@pytest.mark.asyncio
async def test_write_sitemap_from_frontier_roundtrip(tmp_path: Path) -> None:
    domain_dir = tmp_path / "example.com"
    domain_dir.mkdir()
    frontier = Frontier(domain_dir / "_site.sqlite")
    await frontier.open()
    try:
        await frontier.add(
            [
                ("https://example.com/", 0, None),
                ("https://example.com/a", 1, "https://example.com/"),
                ("https://example.com/b", 1, "https://example.com/"),
            ]
        )
        await frontier.mark("https://example.com/", FrontierStatus.DONE)
        await frontier.mark("https://example.com/a", FrontierStatus.DONE)
    finally:
        await frontier.close()
    json_path, md_path = await write_sitemap_from_frontier(
        domain_dir, seed="https://example.com/"
    )
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["total"] == 3
    assert md_path.read_text(encoding="utf-8").count("https://example.com") >= 3
