"""On-disk HTTP cache keyed by URL. Stores ETag + Last-Modified + body.

Used by tier-1 httpx fetcher to skip work on 304 Not Modified.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from gimmethatdata.logging_setup import get_logger

_log = get_logger(__name__)


@dataclass
class CacheEntry:
    url: str
    etag: str | None
    last_modified: str | None
    status_code: int
    headers: dict[str, str]
    body_path: Path

    def conditional_headers(self) -> dict[str, str]:
        out: dict[str, str] = {}
        if self.etag:
            out["If-None-Match"] = self.etag
        if self.last_modified:
            out["If-Modified-Since"] = self.last_modified
        return out


class HttpCache:
    """SHA-keyed cache directory. Lazy, no locking — for single-process use."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def _key(self, url: str) -> str:
        return hashlib.sha1(url.encode("utf-8")).hexdigest()

    def _meta_path(self, url: str) -> Path:
        return self._root / f"{self._key(url)}.json"

    def _body_path(self, url: str) -> Path:
        return self._root / f"{self._key(url)}.bin"

    def lookup(self, url: str) -> CacheEntry | None:
        meta_path = self._meta_path(url)
        if not meta_path.exists():
            return None
        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        body_path = self._body_path(url)
        if not body_path.exists():
            return None
        return CacheEntry(
            url=payload.get("url", url),
            etag=payload.get("etag"),
            last_modified=payload.get("last_modified"),
            status_code=int(payload.get("status_code", 200)),
            headers=payload.get("headers", {}),
            body_path=body_path,
        )

    def store(
        self,
        url: str,
        *,
        status_code: int,
        headers: dict[str, str],
        body: bytes,
    ) -> None:
        normalized = {k.lower(): v for k, v in headers.items()}
        etag = normalized.get("etag")
        last_modified = normalized.get("last-modified")
        if not (etag or last_modified) and status_code != 200:
            return
        self._body_path(url).write_bytes(body)
        self._meta_path(url).write_text(
            json.dumps(
                {
                    "url": url,
                    "etag": etag,
                    "last_modified": last_modified,
                    "status_code": status_code,
                    "headers": normalized,
                }
            ),
            encoding="utf-8",
        )

    def load_body(self, entry: CacheEntry) -> bytes:
        return entry.body_path.read_bytes()
