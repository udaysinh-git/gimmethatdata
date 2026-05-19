"""Tests for export/diff."""

from __future__ import annotations

import json
from pathlib import Path

from gimmethatdata.export.diff import compute_diff, render_diff_markdown


def _seed_page(
    root: Path,
    slug: str,
    *,
    url: str,
    title: str,
    body: str,
) -> None:
    page_dir = root / slug
    page_dir.mkdir(parents=True, exist_ok=True)
    front = (
        "---\n"
        f'url: "{url}"\n'
        f'final_url: "{url}"\n'
        f'title: "{title}"\n'
        "fetched_at: \"2026-05-19T00:00:00+00:00\"\n"
        "---\n\n"
        f"# {title}\n\n{body}\n"
    )
    (page_dir / "content.md").write_text(front, encoding="utf-8")
    (page_dir / "metadata.json").write_text(
        json.dumps({"url": url, "final_url": url, "title": title}),
        encoding="utf-8",
    )


def test_diff_detects_added_removed_changed(tmp_path: Path) -> None:
    before = tmp_path / "before"
    after = tmp_path / "after"
    _seed_page(before, "kept", url="https://x.example/kept", title="Kept", body="same")
    _seed_page(after, "kept", url="https://x.example/kept", title="Kept", body="same")
    _seed_page(before, "gone", url="https://x.example/gone", title="Gone", body="bye")
    _seed_page(after, "fresh", url="https://x.example/new", title="New", body="hi")
    _seed_page(before, "edit", url="https://x.example/edit", title="Edit v1", body="line one")
    _seed_page(after, "edit", url="https://x.example/edit", title="Edit v2", body="line one\nline two")

    result = compute_diff(before, after)
    summary = result.summary()
    assert summary == {"added": 1, "removed": 1, "changed": 1, "unchanged": 1}
    assert result.added[0].url == "https://x.example/new"
    assert result.removed[0].url == "https://x.example/gone"
    assert result.changed[0].url == "https://x.example/edit"
    assert "+line two" in result.changed[0].unified_diff


def test_render_diff_markdown_contains_sections(tmp_path: Path) -> None:
    before = tmp_path / "b"
    after = tmp_path / "a"
    _seed_page(before, "p", url="https://x/p", title="P", body="one")
    _seed_page(after, "p", url="https://x/p", title="P", body="two")
    diff = compute_diff(before, after)
    md = render_diff_markdown(diff)
    assert "Snapshot diff" in md
    assert "Changed pages" in md
    assert "```diff" in md
