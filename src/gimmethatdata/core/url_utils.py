"""URL canonicalization, output-folder derivation, scope checks."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse

from slugify import slugify

_INDEX_SLUG = "_index"
_MAX_SLUG_LEN = 80


def canonicalize(url: str) -> str:
    """Strip fragments + normalize the URL."""
    cleaned, _ = urldefrag(url.strip())
    parsed = urlparse(cleaned)
    scheme = parsed.scheme.lower() or "https"
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/") or "/"
    return urlunparse((scheme, netloc, path, parsed.params, parsed.query, ""))


def absolute(base: str, ref: str) -> str:
    """Resolve `ref` against `base` and return absolute URL."""
    return urljoin(base, ref.strip())


def domain_of(url: str) -> str:
    """Return the network host (lowercased)."""
    netloc = urlparse(url).netloc.lower()
    return netloc.split("@")[-1] or "unknown"


def derive_output_dir(out_root: Path, url: str) -> Path:
    """`<out_root>/<domain>/<slug>` for a given URL."""
    parsed = urlparse(url)
    domain = parsed.netloc.lower() or "unknown"
    path = parsed.path.strip("/")
    if not path:
        slug = _INDEX_SLUG
    else:
        slug = slugify(path, max_length=_MAX_SLUG_LEN, word_boundary=True, save_order=True)
        if not slug:
            slug = _INDEX_SLUG
    if parsed.query:
        qslug = slugify(parsed.query, max_length=40, word_boundary=True)
        if qslug:
            slug = f"{slug}-q-{qslug}"
    return out_root / domain / slug


def is_same_domain(a: str, b: str) -> bool:
    return domain_of(a) == domain_of(b)
