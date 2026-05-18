"""Optional OCR for image-heavy pages via Tesseract."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from gimmethatdata.core.models import AssetKind, AssetRef
from gimmethatdata.logging_setup import get_logger

_log = get_logger(__name__)


def _ocr_image_bytes(body: bytes, *, lang: str = "eng") -> str:
    try:
        import pytesseract
    except ImportError:  # pragma: no cover — `ocr` extra not installed
        _log.warning("ocr_extra_missing")
        return ""
    try:
        with Image.open(io.BytesIO(body)) as img:
            return str(pytesseract.image_to_string(img, lang=lang)).strip()
    except (UnidentifiedImageError, OSError) as exc:
        _log.debug("ocr_image_failed", error=str(exc))
        return ""


def ocr_local_assets(
    assets: list[AssetRef],
    out_dir: Path,
    *,
    lang: str = "eng",
    min_chars: int = 8,
) -> str:
    """Run OCR on every image asset that has a local_path, return aggregate text."""
    chunks: list[str] = []
    for asset in assets:
        if asset.kind is not AssetKind.IMAGE or not asset.local_path:
            continue
        path = out_dir / asset.local_path
        if not path.exists():
            continue
        text = _ocr_image_bytes(path.read_bytes(), lang=lang)
        if len(text) >= min_chars:
            label = asset.alt or path.name
            chunks.append(f"### {label}\n\n{text}")
    return "\n\n".join(chunks)


def append_ocr_section(content_md: str, ocr_text: str) -> str:
    """Append an `## OCR` section to an existing content.md string."""
    if not ocr_text:
        return content_md
    if "## OCR" in content_md:
        return content_md
    return f"{content_md.rstrip()}\n\n## OCR\n\n{ocr_text}\n"
