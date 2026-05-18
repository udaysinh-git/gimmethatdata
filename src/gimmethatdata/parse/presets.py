"""Output presets: vanilla, Obsidian, Logseq."""

from __future__ import annotations

import json
import re
from enum import StrEnum
from urllib.parse import urlparse

from gimmethatdata.core.models import PageMetadata
from gimmethatdata.core.url_utils import domain_of
from gimmethatdata.parse.markdown import html_to_markdown


class Preset(StrEnum):
    VANILLA = "vanilla"
    OBSIDIAN = "obsidian"
    LOGSEQ = "logseq"


def _domain_tag(meta: PageMetadata) -> str:
    domain = domain_of(meta.final_url or meta.url).replace(".", "_")
    return f"gimmethatdata/{domain}"


def _yaml_value(value: object) -> str:
    if isinstance(value, list):
        items = ", ".join(json.dumps(str(v), ensure_ascii=False) for v in value)
        return f"[{items}]"
    return json.dumps(value, ensure_ascii=False)


def _vanilla(meta: PageMetadata, main_html: str) -> str:
    from gimmethatdata.parse.markdown import render_content_md

    return render_content_md(meta, main_html)


def _obsidian(meta: PageMetadata, main_html: str) -> str:
    tags = sorted(
        {
            _domain_tag(meta),
            *([f"lang/{meta.lang}"] if meta.lang else []),
        }
    )
    fields: list[tuple[str, object]] = [
        ("title", meta.title or ""),
        ("url", str(meta.url)),
        ("final_url", str(meta.final_url)),
        ("source", domain_of(meta.final_url or meta.url)),
        ("fetched_at", meta.fetched_at.isoformat()),
        ("tier", meta.tier.value),
        ("status_code", meta.status_code),
        ("tags", tags),
    ]
    front_lines = ["---"]
    for k, v in fields:
        front_lines.append(f"{k}: {_yaml_value(v)}")
    front_lines.append("---")
    body = html_to_markdown(main_html)
    body = _rewrite_internal_links_to_wikilinks(body, base_url=str(meta.final_url))
    title_line = f"# {meta.title}\n\n" if meta.title else ""
    return "\n".join(front_lines) + "\n\n" + title_line + body + "\n"


def _logseq(meta: PageMetadata, main_html: str) -> str:
    body = html_to_markdown(main_html)
    title = meta.title or "Untitled"
    properties = [
        f"url:: {meta.url}",
        f"final-url:: {meta.final_url}",
        f"fetched-at:: {meta.fetched_at.isoformat()}",
        f"tier:: {meta.tier.value}",
        f"source:: {domain_of(meta.final_url or meta.url)}",
    ]
    indented = "\n".join(f"  {line}" if line else "" for line in body.splitlines())
    return (
        f"- # {title}\n"
        + "".join(f"  {p}\n" for p in properties)
        + "\n"
        + indented
        + "\n"
    )


_INTERNAL_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")


def _rewrite_internal_links_to_wikilinks(text: str, *, base_url: str) -> str:
    base_host = urlparse(base_url).netloc

    def repl(match: re.Match[str]) -> str:
        anchor = match.group(1)
        target = match.group(2)
        host = urlparse(target).netloc
        if host and host == base_host:
            return f"[[{target}|{anchor}]]"
        return match.group(0)

    return _INTERNAL_LINK_RE.sub(repl, text)


def render(preset: Preset, meta: PageMetadata, main_html: str) -> str:
    """Render `content.md` for a given preset."""
    if preset is Preset.OBSIDIAN:
        return _obsidian(meta, main_html)
    if preset is Preset.LOGSEQ:
        return _logseq(meta, main_html)
    return _vanilla(meta, main_html)
