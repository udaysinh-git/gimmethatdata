"""Reddit thread / subreddit extractor.

Reddit's public web pages embed the comment tree as JSON at the end of every
listing URL: append `.json` to any thread or subreddit and you get the raw data.
We use that instead of trying to parse Reddit's JS-rendered HTML — it gives us
clean nested comments without any anti-bot fight.
"""

from __future__ import annotations

import html as html_lib
import json
import re
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from gimmethatdata.logging_setup import get_logger
from gimmethatdata.parse.plugins import ExtractedDocument

_log = get_logger(__name__)


_THREAD_RE = re.compile(r"^/r/[^/]+/comments/[^/]+", re.IGNORECASE)
_SUBREDDIT_RE = re.compile(r"^/r/[^/]+/?$", re.IGNORECASE)


@dataclass
class _Comment:
    author: str
    body: str
    score: int
    depth: int


class RedditExtractor:
    """Site plugin for reddit.com URLs."""

    name = "reddit"

    def matches(self, url: str) -> bool:
        parts = urlsplit(url)
        host = parts.netloc.lower()
        if not (host == "reddit.com" or host.endswith(".reddit.com")):
            return False
        path = parts.path
        return bool(_THREAD_RE.search(path) or _SUBREDDIT_RE.search(path))

    def extract(self, html: str, *, url: str) -> ExtractedDocument | None:
        parts = urlsplit(url)
        if not parts.path.endswith(".json"):
            json_url = urlunsplit(
                (parts.scheme or "https", parts.netloc, parts.path.rstrip("/") + ".json", "", "")
            )
        else:
            json_url = url
        payload = _fetch_json(json_url)
        if payload is None:
            return None
        if _THREAD_RE.search(parts.path):
            return self._render_thread(payload)
        if _SUBREDDIT_RE.search(parts.path):
            return self._render_subreddit(payload)
        return None

    def _render_thread(self, payload: Any) -> ExtractedDocument | None:
        if not isinstance(payload, list) or len(payload) < 2:
            return None
        post_listing = payload[0].get("data", {}).get("children", [])
        comments_listing = payload[1].get("data", {}).get("children", [])
        if not post_listing:
            return None
        post = post_listing[0].get("data", {})
        title = post.get("title") or "Reddit thread"
        author = post.get("author") or "[deleted]"
        subreddit = post.get("subreddit_name_prefixed") or post.get("subreddit") or ""
        score = post.get("score", 0)
        selftext = post.get("selftext") or ""
        link_url = post.get("url_overridden_by_dest") or post.get("url") or ""

        body_lines = [
            f"# {title}",
            "",
            f"*posted by u/{author} in {subreddit} — score {score}*",
            "",
        ]
        if selftext:
            body_lines.append(selftext)
            body_lines.append("")
        elif link_url and link_url != post.get("permalink"):
            body_lines.append(f"Link: <{link_url}>")
            body_lines.append("")

        body_lines.append("## Comments")
        body_lines.append("")
        for child in comments_listing:
            self._render_comment(child, depth=0, sink=body_lines)

        md = "\n".join(body_lines)
        return ExtractedDocument(
            main_html=_md_to_simple_html(md),
            title=title,
            extra_meta={
                "reddit_score": str(score),
                "reddit_subreddit": str(subreddit),
                "reddit_author": str(author),
            },
        )

    def _render_subreddit(self, payload: Any) -> ExtractedDocument | None:
        if not isinstance(payload, dict):
            return None
        listings = payload.get("data", {}).get("children", [])
        if not listings:
            return None
        rows = ["# Subreddit listing", ""]
        for entry in listings:
            data = entry.get("data", {})
            title = data.get("title") or "(untitled)"
            author = data.get("author") or "?"
            score = data.get("score", 0)
            permalink = data.get("permalink") or ""
            full = f"https://reddit.com{permalink}" if permalink else ""
            rows.append(f"- **[{title}]({full})** · u/{author} · score {score}")
        md = "\n".join(rows)
        return ExtractedDocument(
            main_html=_md_to_simple_html(md), title="Subreddit listing"
        )

    def _render_comment(self, raw: Any, *, depth: int, sink: list[str]) -> None:
        if not isinstance(raw, dict):
            return
        kind = raw.get("kind")
        data = raw.get("data") or {}
        if kind == "more":
            return
        author = data.get("author") or "[deleted]"
        body = (data.get("body") or "").strip()
        score = data.get("score", 0)
        if body:
            indent = "  " * depth
            sink.append(f"{indent}- **u/{author}** · score {score}")
            for line in body.splitlines():
                sink.append(f"{indent}  > {line}")
            sink.append("")
        replies = data.get("replies")
        if isinstance(replies, dict):
            children = replies.get("data", {}).get("children") or []
            for child in children:
                self._render_comment(child, depth=depth + 1, sink=sink)


def _fetch_json(url: str) -> Any | None:
    """Sync HTTP GET — extractor protocol is sync, no event loop available."""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "gimmethatdata-reddit-extractor/1.0",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read()
    except Exception as exc:
        _log.warning("reddit_json_fetch_failed", url=url, error=str(exc))
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None


def _md_to_simple_html(md: str) -> str:
    """Minimal Markdown -> HTML so the rest of the pipeline can swallow it.

    Doesn't try to be markdownify-grade — just preserves the structure (lists,
    blockquotes, headings) so the later markdownify pass round-trips cleanly.
    """
    lines = md.splitlines()
    out: list[str] = []
    for line in lines:
        if not line.strip():
            out.append("<br>")
            continue
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        prefix = "&nbsp;" * indent
        escaped = html_lib.escape(stripped)
        if stripped.startswith("# "):
            out.append(f"<h1>{escaped[2:]}</h1>")
        elif stripped.startswith("## "):
            out.append(f"<h2>{escaped[3:]}</h2>")
        elif stripped.startswith("- "):
            out.append(f"<p>{prefix}{escaped}</p>")
        elif stripped.startswith("> "):
            out.append(f"<blockquote>{prefix}{escaped[2:]}</blockquote>")
        else:
            out.append(f"<p>{prefix}{escaped}</p>")
    return "\n".join(out)
