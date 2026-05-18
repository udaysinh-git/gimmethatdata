"""Main-content extraction via trafilatura, with selectolax fallback."""

from __future__ import annotations

import trafilatura
from selectolax.parser import HTMLParser


def extract_main_html(html: str, *, url: str | None = None) -> str | None:
    """Return cleaned main-content HTML, or None if extraction fails."""
    result = trafilatura.extract(
        html,
        url=url,
        output_format="html",
        include_comments=False,
        include_tables=True,
        include_images=True,
        include_links=True,
        favor_recall=False,
    )
    return result if result else None


def fallback_main_html(html: str) -> str:
    """Strip scripts/styles/nav and return remaining body HTML."""
    tree = HTMLParser(html)
    for selector in ("script", "style", "noscript", "nav", "footer", "aside", "form"):
        for node in tree.css(selector):
            node.decompose()
    body = tree.css_first("main") or tree.css_first("article") or tree.body
    return body.html if body is not None and body.html else ""
