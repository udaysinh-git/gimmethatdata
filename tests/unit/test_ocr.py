"""Tests for parse/ocr (no Tesseract needed for these)."""

from __future__ import annotations

from gimmethatdata.parse.ocr import append_ocr_section


def test_append_ocr_section_idempotent() -> None:
    base = "---\ntitle: x\n---\n\n# Hello\n\nBody."
    first = append_ocr_section(base, "extracted text")
    second = append_ocr_section(first, "extracted text again")
    assert first.count("## OCR") == 1
    assert second.count("## OCR") == 1
    assert "extracted text" in second


def test_append_ocr_section_skips_empty_text() -> None:
    base = "# Hello"
    assert append_ocr_section(base, "") == base
