"""Tests for parse/pdf_extract."""

from __future__ import annotations

import io

from pypdf import PdfWriter

from gimmethatdata.parse.pdf_extract import (
    is_pdf_response,
    parse_pdf_bytes,
    pdf_to_markdown,
)


def _make_pdf(*, title: str = "Test PDF", author: str = "Test Author") -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_metadata({"/Title": title, "/Author": author})
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_is_pdf_response_by_content_type() -> None:
    assert is_pdf_response(content_type="application/pdf", body=b"%PDF-")
    assert is_pdf_response(content_type="APPLICATION/PDF; charset=utf-8", body=b"")


def test_is_pdf_response_by_magic_bytes() -> None:
    assert is_pdf_response(content_type=None, body=b"%PDF-1.4\nrest")
    assert not is_pdf_response(content_type="text/html", body=b"<html>")


def test_parse_pdf_bytes_extracts_metadata() -> None:
    body = _make_pdf(title="My Paper", author="Jane Doe")
    doc = parse_pdf_bytes(body)
    assert doc is not None
    assert doc.title == "My Paper"
    assert doc.author == "Jane Doe"
    assert doc.page_count == 1


def test_pdf_to_markdown_renders_header() -> None:
    body = _make_pdf(title="Hello", author="World")
    doc = parse_pdf_bytes(body)
    assert doc is not None
    md = pdf_to_markdown(doc)
    assert "# Hello" in md
    assert "*by World*" in md


def test_parse_pdf_returns_none_on_garbage() -> None:
    assert parse_pdf_bytes(b"not a pdf at all") is None
