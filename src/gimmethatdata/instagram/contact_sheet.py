"""Render every downloaded image in a profile as a single browsable HTML grid.

Useful for skimming an archive — much faster than walking folders. Reads
existing `assets.json` files; doesn't touch the network.
"""

from __future__ import annotations

import html as html_lib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_CSS = """
* { box-sizing: border-box; }
body {
  margin: 0; padding: 24px;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: #0d0d0d; color: #ececec;
}
header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 16px; }
header h1 { margin: 0; font-size: 22px; }
header .meta { color: #888; font-size: 13px; }
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 8px;
}
.card {
  position: relative;
  background: #1a1a1a; border-radius: 6px; overflow: hidden;
  aspect-ratio: 1 / 1;
}
.card img { width: 100%; height: 100%; object-fit: cover; display: block; }
.card .overlay {
  position: absolute; left: 0; right: 0; bottom: 0; padding: 6px 8px;
  background: linear-gradient(to top, rgba(0,0,0,0.85), rgba(0,0,0,0));
  font-size: 11px; line-height: 1.3;
}
.card a { color: inherit; text-decoration: none; }
.card .badges { display: flex; gap: 6px; font-size: 10px; color: #ccc; }
.card .badge-reel { color: #ff7a90; }
.card .caption { color: #fff; margin-top: 2px; max-height: 2.6em; overflow: hidden;
                 text-overflow: ellipsis; display: -webkit-box;
                 -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
"""


def _esc(text: str) -> str:
    return html_lib.escape(text or "")


def build_contact_sheet(profile_root: Path, *, max_cells: int | None = None) -> str:
    """Walk posts + reels in chronological order, return a full HTML doc."""
    cells: list[dict[str, Any]] = []
    for kind, subdir in (("post", "posts"), ("reel", "reels"), ("tagged", "tagged")):
        for metadata_path in (profile_root / subdir).rglob("metadata.json"):
            cells.extend(_load_cells(metadata_path, kind=kind))
    cells.sort(key=lambda c: c.get("taken_at") or "", reverse=True)
    if max_cells is not None:
        cells = cells[:max_cells]

    username = profile_root.name
    parts = [
        "<!doctype html>",
        '<html lang="en"><head>',
        '<meta charset="utf-8">',
        f"<title>@{_esc(username)} — contact sheet</title>",
        f"<style>{_CSS}</style>",
        "</head><body>",
        "<header>",
        f"<h1>@{_esc(username)} — contact sheet</h1>",
        f'<div class="meta">{len(cells)} images · generated {datetime.now(UTC).isoformat()}</div>',
        "</header>",
        '<div class="grid">',
    ]
    for cell in cells:
        parts.append(_render_cell(cell, root=profile_root))
    parts.extend(["</div>", "</body></html>"])
    return "\n".join(parts)


def _load_cells(metadata_path: Path, *, kind: str) -> list[dict[str, Any]]:
    try:
        meta = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    assets_path = metadata_path.parent / "assets.json"
    try:
        assets = json.loads(assets_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        assets = []
    if not isinstance(assets, list):
        return []
    out: list[dict[str, Any]] = []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        local = asset.get("local_path")
        if not local:
            continue
        out.append(
            {
                "local_path": str(local),
                "post_dir": metadata_path.parent,
                "shortcode": meta.get("shortcode") or metadata_path.parent.name,
                "url": meta.get("url"),
                "caption": meta.get("caption") or "",
                "taken_at": meta.get("taken_at"),
                "likes": int(meta.get("likes") or 0),
                "comments": int(meta.get("comments_count") or 0),
                "kind": kind,
                "is_video_cover": bool(asset.get("is_video_cover")),
            }
        )
    return out


def _render_cell(cell: dict[str, Any], *, root: Path) -> str:
    img_src = _relative_path(cell["post_dir"] / cell["local_path"], root=root)
    badges = [f"❤ {cell['likes']:,}", f"💬 {cell['comments']}"]
    if cell["kind"] == "reel" or cell["is_video_cover"]:
        badges.insert(0, '<span class="badge-reel">▶ reel</span>')
    elif cell["kind"] == "tagged":
        badges.insert(0, "🏷 tagged")
    caption = (cell["caption"] or "").splitlines()
    first = caption[0] if caption else cell["shortcode"]
    url = cell.get("url") or f"https://www.instagram.com/p/{cell['shortcode']}/"
    return (
        '<div class="card">'
        f'<a href="{_esc(str(url))}" target="_blank">'
        f'<img src="{_esc(img_src)}" alt="{_esc(first[:80])}" loading="lazy">'
        '<div class="overlay">'
        f'<div class="badges">{" ".join(badges)}</div>'
        f'<div class="caption">{_esc(first)}</div>'
        "</div></a></div>"
    )


def _relative_path(path: Path, *, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def write_contact_sheet(profile_root: Path, *, out: Path | None = None) -> Path:
    """Write `_contact_sheet.html` into the profile root by default."""
    html = build_contact_sheet(profile_root)
    target = out or (profile_root / "_contact_sheet.html")
    target.write_text(html, encoding="utf-8")
    return target
