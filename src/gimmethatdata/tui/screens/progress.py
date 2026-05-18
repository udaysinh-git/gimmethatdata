"""Live job execution screen with a streaming event log."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, ProgressBar, RichLog, Static
from textual.worker import Worker, WorkerState

from gimmethatdata.core.pipeline import ScrapeOptions
from gimmethatdata.core.runner import (
    CrawlJobSpec,
    JobEvent,
    ScrapeJobSpec,
    run_crawl_job,
    run_scrape_job,
)
from gimmethatdata.parse.plugins import discover_extractors
from gimmethatdata.tui import log_bridge


class ProgressScreen(Screen[None]):
    """Runs a scrape/crawl job + shows live events."""

    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("c", "cancel", "Cancel"),
        Binding("b", "back", "Back to home"),
    ]

    def __init__(self, *, job_spec: dict[str, Any]) -> None:
        super().__init__()
        self.job_spec = job_spec
        self._sink = log_bridge.TUILogSink()
        self._worker: Worker[Any] | None = None
        self._counts: dict[str, int] = {"done": 0, "failed": 0, "total": 0}
        self._finished = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        kind = self.job_spec.get("kind", "scrape")
        target = self.job_spec.get("seed_url") or ", ".join(self.job_spec.get("urls", [])[:2])
        yield Vertical(
            Static(f"[b]Running {kind}[/b] · {target}", id="banner"),
            ProgressBar(total=100, show_eta=False, id="pbar"),
            Static("done=0  failed=0  total=?", id="counter"),
            RichLog(id="events", highlight=True, markup=True, max_lines=2000, wrap=True),
            Horizontal(
                Button("Cancel (c)", id="cancel-btn", variant="warning"),
                Button("Back to home (b)", id="back-btn"),
            ),
        )
        yield Footer()

    def on_mount(self) -> None:
        log_bridge.install(self._sink, level="INFO")
        self.set_interval(0.25, self._drain_sink)
        self._worker = self.run_worker(self._execute(), exclusive=True, name="job-runner")

    def on_unmount(self) -> None:
        log_bridge.restore()

    async def _execute(self) -> None:
        try:
            await self._dispatch()
        except Exception as exc:
            self.query_one("#events", RichLog).write(f"[red]error[/] {exc!r}")
        finally:
            self._finished = True
            self.query_one("#banner", Static).update(
                f"[b]Finished[/b] · done={self._counts['done']} failed={self._counts['failed']}"
            )

    async def _dispatch(self) -> None:
        kind = self.job_spec["kind"]
        async def on_event(event: JobEvent) -> None:
            self._handle_event(event)

        opts = ScrapeOptions(
            respect_robots=self.job_spec.get("respect_robots", True),
            download_video_embeds=self.job_spec.get("download_videos", False),
            asset_types=self._asset_types(),
            extractors=discover_extractors(),
        )
        if kind == "scrape":
            scrape_spec = ScrapeJobSpec(
                urls=self.job_spec["urls"],
                out=self.job_spec["out"],
                options=opts,
            )
            await run_scrape_job(scrape_spec, on_event=on_event)
        elif kind == "crawl":
            crawl_spec = CrawlJobSpec(
                seed_url=self.job_spec["seed_url"],
                out=self.job_spec["out"],
                depth=self.job_spec.get("depth", 2),
                max_pages=self.job_spec.get("max_pages", 100),
                options=opts,
            )
            await run_crawl_job(crawl_spec, on_event=on_event)
        else:
            self.query_one("#events", RichLog).write(f"[red]unknown job kind:[/] {kind}")

    def _asset_types(self) -> frozenset[Any]:
        from gimmethatdata.core.models import AssetKind

        kinds: set[AssetKind] = set()
        if self.job_spec.get("download_images"):
            kinds.add(AssetKind.IMAGE)
        if self.job_spec.get("download_videos"):
            kinds.add(AssetKind.VIDEO)
        return frozenset(kinds)

    def _handle_event(self, event: JobEvent) -> None:
        pbar = self.query_one("#pbar", ProgressBar)
        if event.kind == "started":
            total = int(event.extra.get("total") or 0) or self._counts["total"]
            self._counts["total"] = total or 1
            pbar.update(total=self._counts["total"], progress=0)
        elif event.kind == "page_done":
            self._counts["done"] += 1
            pbar.update(progress=self._counts["done"] + self._counts["failed"])
        elif event.kind == "page_failed":
            self._counts["failed"] += 1
            pbar.update(progress=self._counts["done"] + self._counts["failed"])
        elif event.kind == "finished":
            pbar.update(progress=pbar.total or self._counts["done"] + self._counts["failed"])
        self._refresh_counter()

    def _refresh_counter(self) -> None:
        c = self._counts
        self.query_one("#counter", Static).update(
            f"done={c['done']}  failed={c['failed']}  total={c['total']}"
        )

    def _drain_sink(self) -> None:
        lines = self._sink.pop_all()
        if not lines:
            return
        log = self.query_one("#events", RichLog)
        for line in lines:
            log.write(line)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state in (WorkerState.SUCCESS, WorkerState.ERROR, WorkerState.CANCELLED):
            self._drain_sink()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.action_cancel()
        elif event.button.id == "back-btn":
            self.action_back()

    def action_cancel(self) -> None:
        if self._worker is not None and not self._finished:
            self._worker.cancel()
            self.query_one("#events", RichLog).write("[yellow]cancel requested[/]")

    def action_back(self) -> None:
        if self._worker is not None and not self._finished:
            self._worker.cancel()
        self.app.pop_screen()


def make_progress_screen(*, out_root: Path, urls: list[str]) -> ProgressScreen:
    """Build a ProgressScreen for a quick scrape — handy in tests."""
    return ProgressScreen(job_spec={"kind": "scrape", "urls": urls, "out": out_root})
