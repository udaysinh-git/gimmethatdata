"""HTML → Markdown conversion with YAML frontmatter."""

from __future__ import annotations

import json
from datetime import datetime

from markdownify import markdownify as _md

from gimmethatdata.core.models import PageMetadata


def html_to_markdown(html: str) -> str:
    """Convert HTML to GitHub-flavored Markdown."""
    if not html:
        return ""
    return str(_md(html, heading_style="ATX", bullets="-", strip=["script", "style"])).strip()


def _yaml_value(value: object) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, datetime):
        return value.isoformat()
    return json.dumps(value, ensure_ascii=False)


def render_frontmatter(meta: PageMetadata) -> str:
    """Render a minimal YAML frontmatter block from PageMetadata."""
    fields: list[tuple[str, object]] = [
        ("url", str(meta.url)),
        ("final_url", str(meta.final_url)),
        ("title", meta.title or ""),
        ("lang", meta.lang or ""),
        ("fetched_at", meta.fetched_at.isoformat()),
        ("status_code", meta.status_code),
        ("tier", meta.tier.value),
    ]
    lines = ["---"]
    for k, v in fields:
        lines.append(f"{k}: {_yaml_value(v)}")
    lines.append("---")
    return "\n".join(lines)


def render_content_md(meta: PageMetadata, body_html: str) -> str:
    """Compose the full content.md: frontmatter + heading + body."""
    front = render_frontmatter(meta)
    body = html_to_markdown(body_html)
    title_line = f"# {meta.title}\n\n" if meta.title else ""
    return f"{front}\n\n{title_line}{body}\n"
