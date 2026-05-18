"""Tests for persist/ledger."""

from __future__ import annotations

from pathlib import Path

import pytest

from gimmethatdata.persist.ledger import JobStatus, Ledger


@pytest.mark.asyncio
async def test_ledger_lifecycle(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "jobs.sqlite")
    await ledger.open()
    try:
        await ledger.create_job("job-1", kind="scrape")
        await ledger.upsert_pending(
            "job-1",
            [
                ("https://a.example/", "https://a.example/"),
                ("https://b.example/", "https://b.example/"),
                ("https://c.example/", "https://c.example/"),
            ],
        )
        pending = await ledger.list_pending("job-1")
        assert sorted(pending) == [
            "https://a.example/",
            "https://b.example/",
            "https://c.example/",
        ]
        await ledger.mark_done("job-1", "https://a.example/", output_dir="out/a", tier="httpx")
        await ledger.mark_failed("job-1", "https://b.example/", "boom")

        pending_after = await ledger.list_pending("job-1")
        assert pending_after == ["https://c.example/"]

        retry = await ledger.list_pending("job-1", retry_failed=True)
        assert sorted(retry) == ["https://b.example/", "https://c.example/"]

        summary = await ledger.job_summary("job-1")
        assert summary == {"done": 1, "failed": 1, "pending": 1}

        await ledger.finish_job("job-1", JobStatus.INTERRUPTED)
        jobs = await ledger.list_jobs()
        assert any(j["id"] == "job-1" and j["status"] == "interrupted" for j in jobs)
    finally:
        await ledger.close()


@pytest.mark.asyncio
async def test_upsert_pending_is_idempotent(tmp_path: Path) -> None:
    ledger = Ledger(tmp_path / "jobs.sqlite")
    await ledger.open()
    try:
        await ledger.create_job("job-1", kind="scrape")
        await ledger.upsert_pending("job-1", [("https://a.example/", "https://a.example/")])
        await ledger.mark_done("job-1", "https://a.example/", output_dir="out/a", tier="httpx")
        await ledger.upsert_pending("job-1", [("https://a.example/", "https://a.example/")])
        summary = await ledger.job_summary("job-1")
        assert summary == {"done": 1}
    finally:
        await ledger.close()
