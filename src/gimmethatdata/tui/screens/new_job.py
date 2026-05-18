"""New-job screen: mode selector + options form. Submits to ProgressScreen."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Checkbox, Footer, Header, Input, RadioButton, RadioSet, Static


class NewJobScreen(Screen[None]):
    """Pick a mode (single / batch / crawl) and configure options."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("ctrl+s", "submit", "Submit"),
    ]

    def __init__(self, *, out_root: Path) -> None:
        super().__init__()
        self.out_root = out_root

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Vertical(
            Static("[b]New job[/b]"),
            Static("Mode:"),
            RadioSet(
                RadioButton("Single page / selected URLs", id="mode-scrape", value=True),
                RadioButton("Full-site crawl", id="mode-crawl"),
                id="mode-set",
            ),
            Static("URLs (one per line for scrape, single seed URL for crawl):"),
            Input(placeholder="https://example.com/", id="url-input"),
            Horizontal(
                Checkbox("Download images", id="opt-images"),
                Checkbox("Download videos", id="opt-videos"),
                Checkbox("Respect robots.txt", id="opt-robots", value=True),
            ),
            Static("Crawl: max depth"),
            Input(placeholder="2", id="depth-input", value="2"),
            Static("Crawl: max pages"),
            Input(placeholder="100", id="max-pages-input", value="100"),
            Horizontal(
                Button("Submit (Ctrl+S)", id="submit-btn", variant="primary"),
                Button("Cancel (Esc)", id="cancel-btn"),
            ),
            Static("", id="msg"),
        )
        yield Footer()

    def action_submit(self) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit-btn":
            self._submit()
        elif event.button.id == "cancel-btn":
            self.app.pop_screen()

    def _gather_urls(self) -> list[str]:
        raw = self.query_one("#url-input", Input).value.strip()
        if not raw:
            return []
        # Single input may hold one URL or many separated by whitespace.
        return [tok for tok in raw.replace("\n", " ").split() if tok.startswith(("http://", "https://"))]

    def _int_or(self, widget_id: str, default: int) -> int:
        raw = self.query_one(widget_id, Input).value.strip()
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError:
            return default

    def _submit(self) -> None:
        urls = self._gather_urls()
        if not urls:
            self.query_one("#msg", Static).update("[red]Provide at least one http(s):// URL[/]")
            return
        radio_set = self.query_one(RadioSet)
        active = radio_set.pressed_button
        mode = active.id if active is not None else "mode-scrape"

        download_images = self.query_one("#opt-images", Checkbox).value
        download_videos = self.query_one("#opt-videos", Checkbox).value
        respect_robots = self.query_one("#opt-robots", Checkbox).value

        from gimmethatdata.tui.screens.progress import ProgressScreen

        job_spec: dict[str, Any]
        if mode == "mode-crawl":
            job_spec = {
                "kind": "crawl",
                "seed_url": urls[0],
                "out": self.out_root,
                "depth": self._int_or("#depth-input", 2),
                "max_pages": self._int_or("#max-pages-input", 100),
                "download_images": download_images,
                "download_videos": download_videos,
                "respect_robots": respect_robots,
            }
        else:
            job_spec = {
                "kind": "scrape",
                "urls": urls,
                "out": self.out_root,
                "download_images": download_images,
                "download_videos": download_videos,
                "respect_robots": respect_robots,
            }
        self.app.push_screen(ProgressScreen(job_spec=job_spec))
