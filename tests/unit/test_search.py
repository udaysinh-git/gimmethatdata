"""Tests for persist/search FTS index."""

from __future__ import annotations

import json
from pathlib import Path

from gimmethatdata.persist.search import SearchIndex, index_all


def _seed_page(root: Path, slug: str, *, url: str, title: str, body: str) -> None:
    page_dir = root / slug
    page_dir.mkdir(parents=True, exist_ok=True)
    (page_dir / "content.md").write_text(
        f"---\nurl: \"{url}\"\nfinal_url: \"{url}\"\ntitle: \"{title}\"\n---\n\n{body}\n",
        encoding="utf-8",
    )
    (page_dir / "metadata.json").write_text(
        json.dumps({"url": url, "final_url": url, "title": title}),
        encoding="utf-8",
    )


def test_index_and_search_hits(tmp_path: Path) -> None:
    _seed_page(
        tmp_path,
        "a",
        url="https://x/blog",
        title="My blog post",
        body="The quick brown fox jumps over the lazy dog.",
    )
    _seed_page(
        tmp_path,
        "b",
        url="https://x/about",
        title="About me",
        body="I write about asynchronous Python and lazy evaluation.",
    )

    indexed = index_all(tmp_path)
    assert indexed == 2

    with SearchIndex(tmp_path / "_search.sqlite") as idx:
        hits = idx.search("lazy")
    urls = {hit.url for hit in hits}
    assert {"https://x/blog", "https://x/about"} == urls
    for hit in hits:
        assert "[match]" in hit.snippet


def test_search_returns_empty_for_blank_query(tmp_path: Path) -> None:
    _seed_page(tmp_path, "a", url="https://x/", title="x", body="content")
    index_all(tmp_path)
    with SearchIndex(tmp_path / "_search.sqlite") as idx:
        assert idx.search("   ") == []
