"""Aggregate `_index.md` generator across multiple scraped pages."""

from __future__ import annotations

from pathlib import Path

from gimmethatdata.core.url_utils import domain_of


def write_index(
    out_root: Path,
    *,
    pages: list[dict[str, str]],
    job_id: str,
) -> Path:
    """Group pages by domain and emit `_index.md` files under each domain dir."""
    by_domain: dict[str, list[dict[str, str]]] = {}
    for page in pages:
        domain = domain_of(page["canonical_url"])
        by_domain.setdefault(domain, []).append(page)

    written: Path | None = None
    for domain, entries in by_domain.items():
        domain_dir = out_root / domain
        if not domain_dir.exists():
            continue
        lines = [
            f"# {domain} — index",
            "",
            f"Job: `{job_id}` · {len(entries)} pages",
            "",
            "| URL | Tier | Output |",
            "| --- | --- | --- |",
        ]
        for entry in entries:
            url = entry["canonical_url"]
            tier = entry.get("tier") or ""
            out_rel = entry.get("output_dir") or ""
            lines.append(f"| <{url}> | {tier} | `{out_rel}` |")
        index_path = domain_dir / "_index.md"
        index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        if written is None:
            written = index_path
    return written or (out_root / "_index.md")
