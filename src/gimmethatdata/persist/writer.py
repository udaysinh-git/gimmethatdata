"""Write a per-page output folder."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from gimmethatdata.core.models import AssetRef, LinkRef, PageMetadata


def _json_default(obj: object) -> object:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _dump_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default),
        encoding="utf-8",
    )


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_page(
    out_dir: Path,
    *,
    content_md: str,
    metadata: PageMetadata,
    assets: list[AssetRef],
    links: list[LinkRef],
    raw_html: bytes | None = None,
) -> None:
    ensure_dir(out_dir)
    (out_dir / "content.md").write_text(content_md, encoding="utf-8")
    _dump_json(out_dir / "metadata.json", metadata.model_dump(mode="json"))
    _dump_json(
        out_dir / "assets.json",
        [a.model_dump(mode="json", by_alias=True) for a in assets],
    )
    _dump_json(
        out_dir / "links.json",
        [link.model_dump(mode="json") for link in links],
    )
    if raw_html is not None:
        (out_dir / "raw.html").write_bytes(raw_html)
