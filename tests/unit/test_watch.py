"""Tests for core/watch."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gimmethatdata.core.watch import latest_snapshot, parse_interval, watch_loop


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("30", 30.0),
        ("30s", 30.0),
        ("5m", 300.0),
        ("1h", 3600.0),
        ("2d", 172800.0),
        ("1.5h", 5400.0),
    ],
)
def test_parse_interval(raw: str, expected: float) -> None:
    assert parse_interval(raw) == expected


def test_parse_interval_rejects_garbage() -> None:
    with pytest.raises(ValueError, match="invalid interval"):
        parse_interval("forever")


def _seed_page(snapshot: Path, slug: str, url: str, body: str) -> None:
    page_dir = snapshot / slug
    page_dir.mkdir(parents=True, exist_ok=True)
    (page_dir / "content.md").write_text(
        f"---\nurl: \"{url}\"\nfinal_url: \"{url}\"\ntitle: \"t\"\n---\n\n{body}\n",
        encoding="utf-8",
    )
    (page_dir / "metadata.json").write_text(
        json.dumps({"url": url, "final_url": url, "title": "t"}),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_watch_loop_runs_and_diffs(tmp_path: Path) -> None:
    counter = {"n": 0}

    async def runner(snapshot_dir: Path) -> None:
        counter["n"] += 1
        body = "first body" if counter["n"] == 1 else "second body"
        _seed_page(snapshot_dir, "p", "https://x/", body)

    ticks: list = []

    async def on_tick(tick) -> None:
        ticks.append(tick)

    await watch_loop(
        interval_seconds=0.01,
        runner=runner,
        snapshots_root=tmp_path,
        iterations=2,
        on_tick=on_tick,
    )

    assert counter["n"] == 2
    assert len(ticks) == 2
    assert ticks[0].diff is None  # first iteration has no prior
    assert ticks[1].diff is not None
    assert ticks[1].diff.summary()["changed"] == 1


def test_latest_snapshot(tmp_path: Path) -> None:
    assert latest_snapshot(tmp_path) is None
    (tmp_path / "20260519-090000").mkdir()
    (tmp_path / "20260519-110000").mkdir()
    (tmp_path / "20260519-100000").mkdir()
    chosen = latest_snapshot(tmp_path)
    assert chosen is not None
    assert chosen.name == "20260519-110000"
