"""Discover media assets and links on a page."""

from __future__ import annotations

from selectolax.parser import HTMLParser, Node

from gimmethatdata.core.models import AssetKind, AssetRef, LinkRef
from gimmethatdata.core.url_utils import absolute, is_same_domain

_MEDIA_EXTS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".avif",
    ".mp4", ".webm", ".mov", ".mkv", ".m4v",
    ".mp3", ".wav", ".ogg", ".m4a", ".flac",
}
_VIDEO_EXTS = {".mp4", ".webm", ".mov", ".mkv", ".m4v"}
_AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".m4a", ".flac"}
_EMBED_HOSTS = {
    "youtube.com", "www.youtube.com", "youtu.be",
    "vimeo.com", "player.vimeo.com",
    "dailymotion.com", "twitch.tv", "player.twitch.tv",
}


def _int_attr(node: Node, name: str) -> int | None:
    val = node.attributes.get(name)
    if not val:
        return None
    try:
        return int(val.strip())
    except (TypeError, ValueError):
        return None


def _ext_of(url: str) -> str:
    path = url.split("?", 1)[0].split("#", 1)[0]
    dot = path.rfind(".")
    return path[dot:].lower() if dot >= 0 else ""


def _classify_link(href: str) -> AssetKind | None:
    ext = _ext_of(href)
    if ext in _VIDEO_EXTS:
        return AssetKind.VIDEO
    if ext in _AUDIO_EXTS:
        return AssetKind.AUDIO
    if ext in _MEDIA_EXTS:
        return AssetKind.IMAGE
    return None


def discover_assets(html: str, base_url: str) -> list[AssetRef]:
    """Walk the DOM and return every media asset reference."""
    tree = HTMLParser(html)
    out: list[AssetRef] = []
    seen: set[tuple[str, str]] = set()

    def push(ref: AssetRef) -> None:
        key = (ref.kind.value, ref.abs_url)
        if key in seen:
            return
        seen.add(key)
        out.append(ref)

    for img in tree.css("img"):
        src = img.attributes.get("src") or img.attributes.get("data-src")
        if not src:
            continue
        push(
            AssetRef(
                kind=AssetKind.IMAGE,
                url=src,
                abs_url=absolute(base_url, src),
                alt=img.attributes.get("alt"),
                title=img.attributes.get("title"),
                width=_int_attr(img, "width"),
                height=_int_attr(img, "height"),
            )
        )

    for video in tree.css("video"):
        src = video.attributes.get("src")
        if src:
            push(
                AssetRef(
                    kind=AssetKind.VIDEO,
                    url=src,
                    abs_url=absolute(base_url, src),
                    title=video.attributes.get("title"),
                )
            )
        for source in video.css("source"):
            ssrc = source.attributes.get("src")
            if not ssrc:
                continue
            push(
                AssetRef(
                    kind=AssetKind.VIDEO,
                    url=ssrc,
                    abs_url=absolute(base_url, ssrc),
                    mime=source.attributes.get("type"),
                )
            )

    for audio in tree.css("audio"):
        src = audio.attributes.get("src")
        if src:
            push(AssetRef(kind=AssetKind.AUDIO, url=src, abs_url=absolute(base_url, src)))
        for source in audio.css("source"):
            ssrc = source.attributes.get("src")
            if not ssrc:
                continue
            push(
                AssetRef(
                    kind=AssetKind.AUDIO,
                    url=ssrc,
                    abs_url=absolute(base_url, ssrc),
                    mime=source.attributes.get("type"),
                )
            )

    for iframe in tree.css("iframe"):
        src = iframe.attributes.get("src")
        if not src:
            continue
        abs_url = absolute(base_url, src)
        if any(host in abs_url for host in _EMBED_HOSTS):
            push(
                AssetRef(
                    kind=AssetKind.EMBED,
                    url=src,
                    abs_url=abs_url,
                    title=iframe.attributes.get("title"),
                    width=_int_attr(iframe, "width"),
                    height=_int_attr(iframe, "height"),
                )
            )

    for link in tree.css("a[href]"):
        href = link.attributes.get("href") or ""
        kind = _classify_link(href)
        if kind is None:
            continue
        push(
            AssetRef(
                kind=kind,
                url=href,
                abs_url=absolute(base_url, href),
                title=link.text(strip=True) or None,
            )
        )

    return out


def discover_links(html: str, base_url: str) -> list[LinkRef]:
    """Return every `<a href>` link as a LinkRef."""
    tree = HTMLParser(html)
    out: list[LinkRef] = []
    seen: set[str] = set()
    for a in tree.css("a[href]"):
        href = a.attributes.get("href") or ""
        if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        abs_url = absolute(base_url, href)
        if abs_url in seen:
            continue
        seen.add(abs_url)
        rel_raw = a.attributes.get("rel") or ""
        rel = [r for r in rel_raw.split() if r]
        out.append(
            LinkRef(
                url=href,
                abs_url=abs_url,
                anchor=a.text(strip=True),
                rel=rel,
                internal=is_same_domain(base_url, abs_url),
            )
        )
    return out
