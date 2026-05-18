"""Textual application entry point."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header

from gimmethatdata.tui.screens.home import HomeScreen


class GimmeApp(App[None]):
    """Top-level Textual application."""

    TITLE = "gimmethatdata"
    SUB_TITLE = "all-in-one async scraper"

    CSS = """
    Screen {
        background: $surface;
    }
    #status-bar {
        dock: bottom;
        height: 1;
        background: $boost;
        color: $text;
    }
    DataTable {
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("n", "new_job", "New job"),
        Binding("question_mark", "help", "Help"),
    ]

    def __init__(self, *, out_root: Path = Path("out")) -> None:
        super().__init__()
        self.out_root = out_root

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Footer()

    async def on_mount(self) -> None:
        await self.push_screen(HomeScreen(out_root=self.out_root))

    def action_new_job(self) -> None:
        from gimmethatdata.tui.screens.new_job import NewJobScreen

        self.push_screen(NewJobScreen(out_root=self.out_root))

    def action_help(self) -> None:
        self.notify(
            "n: new job · r: resume · o: open output · /: filter · q: quit",
            title="Help",
        )


def run_tui(out_root: Path = Path("out")) -> None:
    GimmeApp(out_root=out_root).run()
