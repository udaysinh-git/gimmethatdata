"""Periodically re-scrape a URL or crawl a seed, then diff against the previous
snapshot. Each run lands in `<out>/<job-id>/<timestamp>/` so the diff has a
clear before/after to point at.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from gimmethatdata.core.models import utcnow
from gimmethatdata.export.diff import SnapshotDiff, compute_diff, render_diff_markdown
from gimmethatdata.logging_setup import get_logger

_log = get_logger(__name__)

_DURATION_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*([smhd])?$", re.IGNORECASE)


def parse_interval(raw: str) -> float:
    """Parse '30s' / '5m' / '1h' / '12d' / '90' (seconds) -> float seconds."""
    m = _DURATION_RE.match(raw.strip())
    if not m:
        raise ValueError(f"invalid interval: {raw!r}")
    value = float(m.group(1))
    unit = (m.group(2) or "s").lower()
    multiplier = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
    return value * multiplier


@dataclass
class WatchTick:
    """One iteration of a watch run."""

    index: int
    snapshot_dir: Path
    diff: SnapshotDiff | None  # None on first iteration (no prior snapshot)


async def watch_loop(
    *,
    interval_seconds: float,
    runner: Callable[[Path], Awaitable[None]],
    snapshots_root: Path,
    iterations: int | None = None,
    on_tick: Callable[[WatchTick], Awaitable[None] | None] | None = None,
) -> None:
    """Repeatedly call `runner(snapshot_dir)`, diff against prior, sleep.

    `runner` is responsible for filling `snapshot_dir` with the scrape output
    (we don't care how — single page, batch, or crawl).
    """
    snapshots_root.mkdir(parents=True, exist_ok=True)
    previous: Path | None = None
    index = 0
    while iterations is None or index < iterations:
        index += 1
        snapshot_dir = _unique_snapshot_dir(snapshots_root)
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        _log.info("watch_tick_start", index=index, snapshot=str(snapshot_dir))
        await runner(snapshot_dir)
        diff: SnapshotDiff | None = None
        if previous is not None:
            diff = compute_diff(previous, snapshot_dir)
            (snapshot_dir / "_diff.md").write_text(
                render_diff_markdown(diff), encoding="utf-8"
            )
            _log.info("watch_tick_diff", index=index, **diff.summary())
        previous = snapshot_dir
        tick = WatchTick(index=index, snapshot_dir=snapshot_dir, diff=diff)
        if on_tick is not None:
            result = on_tick(tick)
            if asyncio.iscoroutine(result):
                await result
        if iterations is not None and index >= iterations:
            break
        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            _log.info("watch_cancelled")
            raise


def _unique_snapshot_dir(snapshots_root: Path) -> Path:
    """Pick a timestamped dir that doesn't collide with an existing one."""
    stamp = utcnow().strftime("%Y%m%d-%H%M%S")
    candidate = snapshots_root / stamp
    suffix = 0
    while candidate.exists():
        suffix += 1
        candidate = snapshots_root / f"{stamp}-{suffix:03d}"
    return candidate


def latest_snapshot(snapshots_root: Path) -> Path | None:
    """Return the most recent snapshot dir under `snapshots_root`, or None."""
    if not snapshots_root.exists():
        return None
    candidates = [p for p in snapshots_root.iterdir() if p.is_dir()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.name)
