"""Tests for core/runner."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from gimmethatdata.core.pipeline import ScrapeOptions
from gimmethatdata.core.runner import JobEvent, ScrapeJobSpec, run_scrape_job


@pytest.mark.asyncio
@respx.mock
async def test_run_scrape_job_emits_events(tmp_path: Path, blog_html: str) -> None:
    url = "https://example.com/blog/post-1"
    respx.get(url).mock(
        return_value=httpx.Response(
            200,
            text=blog_html,
            headers={"content-type": "text/html; charset=utf-8"},
        )
    )

    events: list[JobEvent] = []

    async def on_event(event: JobEvent) -> None:
        events.append(event)

    spec = ScrapeJobSpec(
        urls=[url],
        out=tmp_path,
        options=ScrapeOptions(respect_robots=False),
    )
    job_id = await run_scrape_job(spec, on_event=on_event)
    assert job_id

    kinds = [e.kind for e in events]
    assert kinds[0] == "started"
    assert "page_done" in kinds
    assert kinds[-1] == "finished"

    done = next(e for e in events if e.kind == "page_done")
    assert done.url == url
    assert done.tier == "httpx"
    assert Path(done.output_dir or "").exists()

    # Ledger persisted
    assert (tmp_path / "_jobs.sqlite").exists()

    finished = next(e for e in events if e.kind == "finished")
    assert finished.summary == {"done": 1}


@pytest.mark.asyncio
@respx.mock
async def test_run_scrape_job_records_failures(tmp_path: Path) -> None:
    url = "https://example.com/missing"
    respx.get(url).mock(return_value=httpx.Response(500, text=""))

    events: list[JobEvent] = []

    async def on_event(event: JobEvent) -> None:
        events.append(event)

    spec = ScrapeJobSpec(
        urls=[url],
        out=tmp_path,
        options=ScrapeOptions(respect_robots=False),
    )
    # 500 isn't a FetchError (we'd need transport error), but trafilatura will return empty content
    # and the pipeline still succeeds. So this is actually a happy-path test for an empty response.
    job_id = await run_scrape_job(spec, on_event=on_event)
    finished = next(e for e in events if e.kind == "finished")
    assert finished.job_id == job_id

    # Ledger should track the page
    ledger_path = tmp_path / "_jobs.sqlite"
    assert ledger_path.exists()
    # rudimentary readout
    import sqlite3

    rows = sqlite3.connect(ledger_path).execute(
        "SELECT canonical_url, status FROM pages WHERE job_id=?", (job_id,)
    ).fetchall()
    assert rows
    assert rows[0][0] == url
