"""Extract page metadata: title, og:*, twitter:*, JSON-LD, headings, meta tags."""

from __future__ import annotations

import json
from typing import Any

from selectolax.parser import HTMLParser, Node


def _attr(node: Node | None, name: str) -> str | None:
    if node is None:
        return None
    val = node.attributes.get(name)
    return val.strip() if val else None


def _text(node: Node | None) -> str | None:
    if node is None:
        return None
    text = node.text(strip=True)
    return text or None


def extract_meta(html: str) -> dict[str, Any]:
    """Return a flat dict of page metadata, ready to merge into PageMetadata."""
    tree = HTMLParser(html)

    title = _text(tree.css_first("title"))
    description = _attr(tree.css_first('meta[name="description"]'), "content")
    lang = _attr(tree.css_first("html"), "lang")
    canonical = _attr(tree.css_first('link[rel="canonical"]'), "href")

    meta: dict[str, str] = {}
    og: dict[str, str] = {}
    twitter: dict[str, str] = {}
    for node in tree.css("meta"):
        name = node.attributes.get("name") or ""
        prop = node.attributes.get("property") or ""
        content = node.attributes.get("content") or ""
        if not content:
            continue
        key = (prop or name).lower()
        if not key:
            continue
        if key.startswith("og:"):
            og[key[3:]] = content
        elif key.startswith("twitter:"):
            twitter[key[8:]] = content
        else:
            meta[key] = content

    headings: dict[str, list[str]] = {}
    for level in ("h1", "h2", "h3"):
        items = [n.text(strip=True) for n in tree.css(level) if n.text(strip=True)]
        if items:
            headings[level] = items

    jsonld: list[dict[str, Any]] = []
    for script in tree.css('script[type="application/ld+json"]'):
        raw = script.text() or ""
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, list):
            jsonld.extend(item for item in payload if isinstance(item, dict))
        elif isinstance(payload, dict):
            jsonld.append(payload)

    return {
        "title": title,
        "description": description,
        "lang": lang,
        "canonical": canonical,
        "headings": headings,
        "meta": meta,
        "og": og,
        "twitter": twitter,
        "jsonld": jsonld,
    }
