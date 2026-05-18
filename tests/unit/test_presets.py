"""Tests for parse/presets."""

from __future__ import annotations

from datetime import UTC, datetime

from gimmethatdata.core.models import FetchTier, PageMetadata
from gimmethatdata.parse.presets import Preset, render


def _meta(**overrides: object) -> PageMetadata:
    base: dict[str, object] = {
        "url": "https://example.com/blog/post",
        "final_url": "https://example.com/blog/post",
        "title": "Hello",
        "lang": "en",
        "status_code": 200,
        "tier": FetchTier.HTTPX,
        "elapsed_ms": 100,
        "fetched_at": datetime(2026, 5, 19, 3, 14, 15, tzinfo=UTC),
    }
    base.update(overrides)
    return PageMetadata(**base)  # type: ignore[arg-type]


SAMPLE_HTML = (
    '<p>See the <a href="https://example.com/about">about page</a> '
    'or <a href="https://other.com/">other.com</a>.</p>'
)


def test_vanilla_preset_has_yaml_frontmatter_and_h1() -> None:
    output = render(Preset.VANILLA, _meta(), SAMPLE_HTML)
    assert output.startswith("---")
    assert "tier: \"httpx\"" in output
    assert "# Hello" in output


def test_obsidian_preset_emits_tags_and_wikilinks() -> None:
    output = render(Preset.OBSIDIAN, _meta(), SAMPLE_HTML)
    assert "tags: [" in output
    assert "gimmethatdata/example_com" in output
    assert "lang/en" in output
    assert "[[https://example.com/about|about page]]" in output
    assert "[other.com](https://other.com/)" in output


def test_logseq_preset_uses_block_syntax() -> None:
    output = render(Preset.LOGSEQ, _meta(), SAMPLE_HTML)
    assert output.startswith("- # Hello")
    assert "url:: https://example.com/blog/post" in output
    assert "tier:: httpx" in output
