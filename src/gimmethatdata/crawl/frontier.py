"""SQLite-backed URL frontier with dedup, depth, and scope filtering."""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path

import aiosqlite

from gimmethatdata.core.models import utcnow
from gimmethatdata.core.url_utils import canonicalize, domain_of

_SCHEMA = """
CREATE TABLE IF NOT EXISTS frontier (
    canonical_url TEXT PRIMARY KEY,
    depth INTEGER NOT NULL,
    status TEXT NOT NULL,
    discovered_at TEXT NOT NULL,
    parent_url TEXT
);
CREATE INDEX IF NOT EXISTS idx_frontier_status ON frontier(status);
CREATE TABLE IF NOT EXISTS site_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


class FrontierStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class ScopeMode(StrEnum):
    SAME_DOMAIN = "same-domain"
    SAME_HOST = "same-host"
    ALLOWLIST = "allowlist"


class ScopeRule:
    """Decides whether a discovered URL is in scope."""

    def __init__(
        self,
        *,
        mode: ScopeMode = ScopeMode.SAME_DOMAIN,
        seed: str,
        allow_patterns: list[str] | None = None,
        deny_patterns: list[str] | None = None,
    ) -> None:
        self._mode = mode
        self._seed_host = domain_of(seed)
        self._seed_domain = self._seed_host
        self._allow = [self._compile(p) for p in (allow_patterns or [])]
        self._deny = [self._compile(p) for p in (deny_patterns or [])]

    @staticmethod
    def _compile(pattern: str) -> re.Pattern[str]:
        return re.compile(fnmatch.translate(pattern))

    def includes(self, url: str) -> bool:
        for deny in self._deny:
            if deny.match(url):
                return False
        if self._mode is ScopeMode.ALLOWLIST:
            return any(allow.match(url) for allow in self._allow)
        host = domain_of(url)
        if self._mode is ScopeMode.SAME_HOST:
            return host == self._seed_host
        return host == self._seed_domain or host.endswith("." + self._seed_domain)


class Frontier:
    """Async sqlite-backed frontier."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._conn: aiosqlite.Connection | None = None

    async def open(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    def _require(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Frontier not open")
        return self._conn

    async def add(self, urls: Sequence[tuple[str, int, str | None]]) -> int:
        """Insert (url, depth, parent) tuples. Returns count actually inserted."""
        conn = self._require()
        if not urls:
            return 0
        now = utcnow().isoformat()
        rows = [
            (canonicalize(u), depth, FrontierStatus.PENDING.value, now, parent)
            for u, depth, parent in urls
        ]
        cursor = await conn.executemany(
            "INSERT OR IGNORE INTO frontier "
            "(canonical_url, depth, status, discovered_at, parent_url) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        await conn.commit()
        return cursor.rowcount or 0

    async def claim_next(self) -> tuple[str, int] | None:
        conn = self._require()
        async with conn.execute(
            "SELECT canonical_url, depth FROM frontier WHERE status=? "
            "ORDER BY depth ASC, discovered_at ASC LIMIT 1",
            (FrontierStatus.PENDING.value,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        await conn.execute(
            "UPDATE frontier SET status=? WHERE canonical_url=?",
            (FrontierStatus.IN_PROGRESS.value, row["canonical_url"]),
        )
        await conn.commit()
        return row["canonical_url"], row["depth"]

    async def mark(self, url: str, status: FrontierStatus) -> None:
        conn = self._require()
        await conn.execute(
            "UPDATE frontier SET status=? WHERE canonical_url=?",
            (status.value, canonicalize(url)),
        )
        await conn.commit()

    async def summary(self) -> dict[str, int]:
        conn = self._require()
        async with conn.execute(
            "SELECT status, COUNT(*) AS c FROM frontier GROUP BY status"
        ) as cursor:
            rows = await cursor.fetchall()
        return {row["status"]: row["c"] for row in rows}

    async def count_done(self) -> int:
        conn = self._require()
        async with conn.execute(
            "SELECT COUNT(*) FROM frontier WHERE status=?",
            (FrontierStatus.DONE.value,),
        ) as cursor:
            row = await cursor.fetchone()
        return int(row[0]) if row else 0

    async def dump_all(self) -> list[dict[str, str | int | None]]:
        """Return every row in the frontier — full discovery graph."""
        conn = self._require()
        async with conn.execute(
            "SELECT canonical_url, depth, status, discovered_at, parent_url "
            "FROM frontier ORDER BY depth ASC, discovered_at ASC"
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            {
                "canonical_url": row["canonical_url"],
                "depth": row["depth"],
                "status": row["status"],
                "discovered_at": row["discovered_at"],
                "parent_url": row["parent_url"],
            }
            for row in rows
        ]
