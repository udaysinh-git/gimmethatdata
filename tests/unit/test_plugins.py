"""Tests for parse/plugins."""

from __future__ import annotations

from gimmethatdata.parse.plugins import ExtractedDocument, Extractor, select_extractor


class _FakeExtractor:
    """In-test extractor that matches example.com paths."""

    name = "fake-example"

    def matches(self, url: str) -> bool:
        return "example.com" in url

    def extract(self, html: str, *, url: str) -> ExtractedDocument | None:
        if "<article>" not in html:
            return None
        body = html.split("<article>", 1)[1].split("</article>", 1)[0]
        return ExtractedDocument(main_html=f"<article>{body}</article>", title="Plugin Title")


def test_protocol_runtime_check() -> None:
    ex = _FakeExtractor()
    assert isinstance(ex, Extractor)


def test_select_extractor_matches() -> None:
    extractors: list[Extractor] = [_FakeExtractor()]
    picked = select_extractor(extractors, "https://example.com/x")
    assert picked is not None and picked.name == "fake-example"


def test_select_extractor_skips_when_no_match() -> None:
    picked = select_extractor([_FakeExtractor()], "https://other.com/")
    assert picked is None


def test_extract_returns_document() -> None:
    doc = _FakeExtractor().extract(
        "<html><article>Hello</article></html>", url="https://example.com/"
    )
    assert doc is not None
    assert "Hello" in doc.main_html
    assert doc.title == "Plugin Title"
