"""robots.txt + sitemap.xml discovery for seeding the frontier."""

from __future__ import annotations

import gzip
import re
from urllib.parse import urljoin, urlparse

import httpx

from gimmethatdata.logging_setup import get_logger

_log = get_logger(__name__)

_SITEMAP_RE = re.compile(r"^\s*Sitemap:\s*(\S+)\s*$", re.IGNORECASE | re.MULTILINE)
_URL_TAG_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.IGNORECASE)


async def _fetch(client: httpx.AsyncClient, url: str) -> bytes | None:
    try:
        response = await client.get(url)
        if response.status_code >= 400:
            return None
        return response.content
    except httpx.HTTPError as exc:
        _log.debug("sitemap_fetch_failed", url=url, error=str(exc))
        return None


def _maybe_gunzip(url: str, payload: bytes) -> bytes:
    if url.endswith(".gz") or payload[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(payload)
        except OSError:
            return payload
    return payload


def _parse_urls(payload: bytes) -> list[str]:
    text = payload.decode("utf-8", errors="replace")
    return [m.group(1) for m in _URL_TAG_RE.finditer(text)]


def _parse_sitemap_index(payload: bytes) -> list[str]:
    return _parse_urls(payload)


async def discover_sitemap_urls(seed_url: str, *, user_agent: str) -> list[str]:
    """Return URLs discovered via robots.txt → sitemap.xml chains."""
    parsed = urlparse(seed_url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    discovered: set[str] = set()
    queue: list[str] = []
    async with httpx.AsyncClient(
        timeout=20.0,
        follow_redirects=True,
        headers={"User-Agent": user_agent},
    ) as client:
        robots_body = await _fetch(client, urljoin(base, "/robots.txt"))
        if robots_body is not None:
            text = robots_body.decode("utf-8", errors="replace")
            for match in _SITEMAP_RE.finditer(text):
                queue.append(match.group(1).strip())
        if not queue:
            queue.append(urljoin(base, "/sitemap.xml"))

        seen_sitemaps: set[str] = set()
        while queue:
            sm_url = queue.pop(0)
            if sm_url in seen_sitemaps:
                continue
            seen_sitemaps.add(sm_url)
            body = await _fetch(client, sm_url)
            if body is None:
                continue
            body = _maybe_gunzip(sm_url, body)
            urls = _parse_urls(body)
            if not urls:
                continue
            if "<sitemapindex" in body[:2048].decode("utf-8", errors="replace").lower():
                queue.extend(_parse_sitemap_index(body))
                continue
            discovered.update(urls)

    return sorted(discovered)
