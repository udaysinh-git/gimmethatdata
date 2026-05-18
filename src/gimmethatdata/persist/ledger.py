"""SQLite-backed job + page ledger for resume support."""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Any

import aiosqlite

from gimmethatdata.core.models import utcnow

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    options_json TEXT
);
CREATE TABLE IF NOT EXISTS pages (
    job_id TEXT NOT NULL,
    url TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    status TEXT NOT NULL,
    output_dir TEXT,
    tier TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (job_id, canonical_url),
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_pages_job_status ON pages(job_id, status);
"""


class PageStatus(StrEnum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class JobStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


class Ledger:
    """Async-friendly wrapper around a sqlite ledger file."""

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
            raise RuntimeError("Ledger is not open")
        return self._conn

    async def create_job(
        self,
        job_id: str,
        *,
        kind: str,
        options: dict[str, Any] | None = None,
    ) -> None:
        conn = self._require()
        await conn.execute(
            "INSERT OR REPLACE INTO jobs (id, kind, status, started_at, options_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                job_id,
                kind,
                JobStatus.RUNNING.value,
                utcnow().isoformat(),
                json.dumps(options or {}),
            ),
        )
        await conn.commit()

    async def finish_job(self, job_id: str, status: JobStatus) -> None:
        conn = self._require()
        await conn.execute(
            "UPDATE jobs SET status = ?, finished_at = ? WHERE id = ?",
            (status.value, utcnow().isoformat(), job_id),
        )
        await conn.commit()

    async def upsert_pending(self, job_id: str, urls: list[tuple[str, str]]) -> None:
        """Insert pages as pending if they don't already exist."""
        conn = self._require()
        now = utcnow().isoformat()
        await conn.executemany(
            "INSERT OR IGNORE INTO pages "
            "(job_id, url, canonical_url, status, attempts, updated_at) "
            "VALUES (?, ?, ?, ?, 0, ?)",
            [(job_id, url, canonical, PageStatus.PENDING.value, now) for url, canonical in urls],
        )
        await conn.commit()

    async def mark_done(
        self,
        job_id: str,
        canonical_url: str,
        *,
        output_dir: str,
        tier: str,
    ) -> None:
        conn = self._require()
        await conn.execute(
            "UPDATE pages SET status=?, output_dir=?, tier=?, updated_at=?, last_error=NULL "
            "WHERE job_id=? AND canonical_url=?",
            (PageStatus.DONE.value, output_dir, tier, utcnow().isoformat(), job_id, canonical_url),
        )
        await conn.commit()

    async def mark_failed(self, job_id: str, canonical_url: str, error: str) -> None:
        conn = self._require()
        await conn.execute(
            "UPDATE pages SET status=?, attempts=attempts+1, last_error=?, updated_at=? "
            "WHERE job_id=? AND canonical_url=?",
            (PageStatus.FAILED.value, error[:1000], utcnow().isoformat(), job_id, canonical_url),
        )
        await conn.commit()

    async def list_pending(self, job_id: str, *, retry_failed: bool = False) -> list[str]:
        conn = self._require()
        statuses = [PageStatus.PENDING.value]
        if retry_failed:
            statuses.append(PageStatus.FAILED.value)
        placeholders = ",".join("?" for _ in statuses)
        async with conn.execute(
            f"SELECT canonical_url FROM pages WHERE job_id=? AND status IN ({placeholders})",
            (job_id, *statuses),
        ) as cursor:
            rows = await cursor.fetchall()
        return [row["canonical_url"] for row in rows]

    async def job_summary(self, job_id: str) -> dict[str, int]:
        conn = self._require()
        async with conn.execute(
            "SELECT status, COUNT(*) as c FROM pages WHERE job_id=? GROUP BY status",
            (job_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return {row["status"]: row["c"] for row in rows}

    async def list_jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        conn = self._require()
        async with conn.execute(
            "SELECT id, kind, status, started_at, finished_at FROM jobs "
            "ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def list_done_pages(self, job_id: str) -> list[dict[str, Any]]:
        conn = self._require()
        async with conn.execute(
            "SELECT canonical_url, output_dir, tier, updated_at FROM pages "
            "WHERE job_id=? AND status=? ORDER BY updated_at",
            (job_id, PageStatus.DONE.value),
        ) as cursor:
            rows = await cursor.fetchall()
        return [dict(row) for row in rows]


def make_job_id() -> str:
    return utcnow().strftime("job-%Y%m%d-%H%M%S")
