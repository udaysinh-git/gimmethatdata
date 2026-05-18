"""Build our own discovered sitemap from the frontier — JSON + tree-rendered MD."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from gimmethatdata.core.models import utcnow
from gimmethatdata.crawl.frontier import Frontier


def _shorten(url: str, max_len: int = 80) -> str:
    return url if len(url) <= max_len else url[: max_len - 1] + "…"


def _render_tree(
    nodes: list[dict[str, Any]],
    *,
    seed: str | None,
) -> str:
    """Render the discovery graph as an indented Markdown tree."""
    by_url = {n["canonical_url"]: n for n in nodes}
    children: dict[str | None, list[str]] = defaultdict(list)
    for node in nodes:
        children[node["parent_url"]].append(node["canonical_url"])

    roots: list[str]
    if seed is not None and seed in by_url:
        roots = [seed]
    else:
        roots = sorted(children.get(None, []))
        if not roots:
            roots = sorted({n["canonical_url"] for n in nodes if not n["parent_url"]})

    lines: list[str] = []
    visited: set[str] = set()

    def emit(url: str, depth: int) -> None:
        if url in visited:
            lines.append(f"{'  ' * depth}- ↻ {_shorten(url)}")
            return
        visited.add(url)
        node = by_url.get(url)
        status = node["status"] if node else "unknown"
        badge = {
            "done": "✓",
            "failed": "✗",
            "skipped": "↷",
            "pending": "…",
            "in_progress": "▶",
        }.get(str(status), "?")
        lines.append(f"{'  ' * depth}- {badge} `{_shorten(url)}` [{status}]")
        for child in sorted(children.get(url, [])):
            emit(child, depth + 1)

    for root in roots:
        emit(root, 0)

    # Orphans (nodes whose parent isn't in the dump) — list at the end.
    orphans = sorted(
        {
            n["canonical_url"]
            for n in nodes
            if n["canonical_url"] not in visited
        }
    )
    if orphans:
        lines.append("")
        lines.append("## Orphans (discovered without a parent in scope)")
        for orphan in orphans:
            emit(orphan, 0)
    return "\n".join(lines)


def _serializable(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Coerce sqlite Row values into plain JSON types."""
    return [
        {
            "canonical_url": str(n["canonical_url"]),
            "depth": int(n["depth"]) if n["depth"] is not None else None,
            "status": str(n["status"]),
            "discovered_at": str(n["discovered_at"]),
            "parent_url": str(n["parent_url"]) if n["parent_url"] else None,
        }
        for n in nodes
    ]


def write_sitemap(
    domain_dir: Path,
    *,
    nodes: list[dict[str, Any]],
    seed: str | None = None,
) -> tuple[Path, Path]:
    """Emit `_sitemap.json` and `_sitemap.md` under `domain_dir`."""
    domain_dir.mkdir(parents=True, exist_ok=True)
    serial = _serializable(nodes)
    counts: dict[str, int] = defaultdict(int)
    for node in serial:
        counts[node["status"]] += 1

    payload: dict[str, Any] = {
        "generated_at": utcnow().isoformat(),
        "seed": seed,
        "total": len(serial),
        "counts": dict(counts),
        "nodes": serial,
        "edges": [
            {"parent": n["parent_url"], "child": n["canonical_url"]}
            for n in serial
            if n["parent_url"]
        ],
    }
    json_path = domain_dir / "_sitemap.json"
    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    md_path = domain_dir / "_sitemap.md"
    tree = _render_tree(serial, seed=seed)
    counts_str = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    md_path.write_text(
        f"# Sitemap — {domain_dir.name}\n\n"
        f"Generated: `{payload['generated_at']}`\n"
        f"Seed: `{seed or '(none recorded)'}`\n"
        f"Total: {len(serial)} ({counts_str})\n\n"
        f"## Discovery tree\n\n"
        f"{tree}\n",
        encoding="utf-8",
    )
    return json_path, md_path


async def write_sitemap_from_frontier(
    domain_dir: Path,
    *,
    seed: str | None = None,
) -> tuple[Path, Path]:
    """Open `_site.sqlite` under `domain_dir` and write the sitemap files."""
    site_db = domain_dir / "_site.sqlite"
    frontier = Frontier(site_db)
    await frontier.open()
    try:
        nodes = await frontier.dump_all()
    finally:
        await frontier.close()
    return write_sitemap(domain_dir, nodes=nodes, seed=seed)
