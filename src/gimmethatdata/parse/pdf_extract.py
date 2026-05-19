"""Extract text + metadata from a PDF response into the same shape an HTML
page would produce, so the rest of the pipeline doesn't have to special-case it.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any

from gimmethatdata.logging_setup import get_logger

_log = get_logger(__name__)


@dataclass
class PdfDocument:
    """Result of parsing PDF bytes."""

    title: str | None
    author: str | None
    page_count: int
    text: str
    meta: dict[str, str]


def is_pdf_response(*, content_type: str | None, body: bytes) -> bool:
    """Detect whether a response is a PDF by content-type or magic bytes."""
    if content_type and "application/pdf" in content_type.lower():
        return True
    return body[:5] == b"%PDF-"


def parse_pdf_bytes(body: bytes) -> PdfDocument | None:
    """Return text + metadata from PDF bytes, or None on failure."""
    try:
        from pypdf import PdfReader
    except ImportError:
        _log.warning("pypdf_missing — install with `uv sync --extra media`")
        return None
    try:
        reader = PdfReader(io.BytesIO(body))
    except Exception as exc:
        _log.warning("pdf_read_failed", error=str(exc))
        return None

    pages_text: list[str] = []
    for index, page in enumerate(reader.pages):
        try:
            pages_text.append(page.extract_text() or "")
        except Exception as exc:
            _log.debug("pdf_page_extract_failed", index=index, error=str(exc))
            pages_text.append("")
    text = "\n\n".join(t.strip() for t in pages_text if t.strip())

    info: dict[str, Any] = {}
    if reader.metadata is not None:
        for k, v in reader.metadata.items():
            if v is None:
                continue
            key = str(k).lstrip("/").lower()
            info[key] = str(v)

    return PdfDocument(
        title=info.get("title"),
        author=info.get("author"),
        page_count=len(reader.pages),
        text=text,
        meta=info,
    )


def pdf_to_markdown(doc: PdfDocument) -> str:
    """Render a PdfDocument as a simple Markdown body (used by the pipeline)."""
    lines: list[str] = []
    if doc.title:
        lines.append(f"# {doc.title}")
    if doc.author:
        lines.append(f"*by {doc.author}*")
    lines.append(f"_{doc.page_count} pages_")
    lines.append("")
    lines.append(doc.text)
    return "\n\n".join(lines)
