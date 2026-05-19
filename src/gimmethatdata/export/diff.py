"""Compute the diff between two scrape snapshots.

A snapshot is any folder containing per-page subdirs that each hold a
`content.md` (the same layout we write). The diff is by canonical URL,
discovered from each page's `metadata.json` (with a filename fallback).
"""

from __future__ import annotations

import difflib
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class PageRecord:
    url: str
    output_dir: Path
    title: str | None
    content_md: str
    sha: str


@dataclass
class PageChange:
    url: str
    title_before: str | None
    title_after: str | None
    sha_before: str
    sha_after: str
    unified_diff: str


@dataclass
class SnapshotDiff:
    added: list[PageRecord]
    removed: list[PageRecord]
    changed: list[PageChange]
    unchanged: int

    @property
    def total_after(self) -> int:
        return len(self.added) + len(self.changed) + self.unchanged

    def summary(self) -> dict[str, int]:
        return {
            "added": len(self.added),
            "removed": len(self.removed),
            "changed": len(self.changed),
            "unchanged": self.unchanged,
        }


def _read_snapshot(root: Path) -> dict[str, PageRecord]:
    """Load every page under `root` keyed by its canonical URL."""
    pages: dict[str, PageRecord] = {}
    for md_path in sorted(root.rglob("content.md")):
        page_dir = md_path.parent
        content = md_path.read_text(encoding="utf-8")
        sha = hashlib.sha256(_strip_frontmatter(content).encode("utf-8")).hexdigest()
        metadata = _read_metadata(page_dir)
        url = metadata.get("final_url") or metadata.get("url") or str(page_dir)
        pages[str(url)] = PageRecord(
            url=str(url),
            output_dir=page_dir,
            title=metadata.get("title"),
            content_md=content,
            sha=sha,
        )
    return pages


def _read_metadata(page_dir: Path) -> dict[str, Any]:
    path = page_dir / "metadata.json"
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _strip_frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---", 4)
    if end < 0:
        return text
    return text[end + 4 :].lstrip("\n")


def compute_diff(before_root: Path, after_root: Path) -> SnapshotDiff:
    """Diff two snapshot folders by canonical URL."""
    before = _read_snapshot(before_root)
    after = _read_snapshot(after_root)

    before_urls = set(before)
    after_urls = set(after)

    added = [after[u] for u in sorted(after_urls - before_urls)]
    removed = [before[u] for u in sorted(before_urls - after_urls)]

    changed: list[PageChange] = []
    unchanged = 0
    for url in sorted(before_urls & after_urls):
        a, b = before[url], after[url]
        if a.sha == b.sha:
            unchanged += 1
            continue
        ud = "\n".join(
            difflib.unified_diff(
                _strip_frontmatter(a.content_md).splitlines(),
                _strip_frontmatter(b.content_md).splitlines(),
                fromfile=f"before/{url}",
                tofile=f"after/{url}",
                lineterm="",
            )
        )
        changed.append(
            PageChange(
                url=url,
                title_before=a.title,
                title_after=b.title,
                sha_before=a.sha,
                sha_after=b.sha,
                unified_diff=ud,
            )
        )

    return SnapshotDiff(added=added, removed=removed, changed=changed, unchanged=unchanged)


def render_diff_markdown(diff: SnapshotDiff) -> str:
    """Human-readable Markdown summary of the diff."""
    summary = diff.summary()
    lines = [
        "# Snapshot diff",
        "",
        f"- Added: {summary['added']}",
        f"- Removed: {summary['removed']}",
        f"- Changed: {summary['changed']}",
        f"- Unchanged: {summary['unchanged']}",
        "",
    ]
    if diff.added:
        lines.append("## Added pages")
        lines.append("")
        for page in diff.added:
            lines.append(f"- **{page.title or '(untitled)'}** · `{page.url}`")
        lines.append("")
    if diff.removed:
        lines.append("## Removed pages")
        lines.append("")
        for page in diff.removed:
            lines.append(f"- **{page.title or '(untitled)'}** · `{page.url}`")
        lines.append("")
    if diff.changed:
        lines.append("## Changed pages")
        lines.append("")
        for change in diff.changed:
            lines.append(f"### {change.title_after or change.url}")
            lines.append("")
            lines.append(f"`{change.url}`")
            lines.append("")
            lines.append("```diff")
            lines.append(change.unified_diff or "(content shifted; sha changed)")
            lines.append("```")
            lines.append("")
    return "\n".join(lines)
