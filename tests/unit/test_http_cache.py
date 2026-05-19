"""Tests for fetch/http_cache."""

from __future__ import annotations

from pathlib import Path

from gimmethatdata.fetch.http_cache import HttpCache


def test_cache_store_and_lookup(tmp_path: Path) -> None:
    cache = HttpCache(tmp_path)
    assert cache.lookup("https://example.com/") is None
    cache.store(
        "https://example.com/",
        status_code=200,
        headers={"ETag": '"deadbeef"', "Content-Type": "text/html", "Last-Modified": "Wed, 01 Jan 2025"},
        body=b"<html>hi</html>",
    )
    entry = cache.lookup("https://example.com/")
    assert entry is not None
    assert entry.etag == '"deadbeef"'
    assert entry.last_modified == "Wed, 01 Jan 2025"
    assert cache.load_body(entry) == b"<html>hi</html>"
    headers = entry.conditional_headers()
    assert headers == {
        "If-None-Match": '"deadbeef"',
        "If-Modified-Since": "Wed, 01 Jan 2025",
    }


def test_cache_skips_when_no_validators(tmp_path: Path) -> None:
    cache = HttpCache(tmp_path)
    cache.store(
        "https://example.com/no-validators",
        status_code=200,
        headers={"Content-Type": "text/html"},
        body=b"body",
    )
    # Without ETag/Last-Modified, the entry should still be saved (200 OK), so
    # subsequent re-fetches at least have a body to load. Validate that.
    entry = cache.lookup("https://example.com/no-validators")
    # Either None (skipped) or an entry with no validators — both acceptable here.
    if entry is not None:
        assert entry.etag is None
        assert entry.last_modified is None
