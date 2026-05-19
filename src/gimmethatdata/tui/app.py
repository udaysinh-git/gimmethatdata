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
        Binding("s", "open_search", "Search"),
        Binding("m", "open_sitemap", "Sitemap"),
        Binding("d", "open_diff", "Diff"),
        Binding("i", "open_instagram", "Instagram"),
        Binding("comma", "open_settings", "Settings"),
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

    def action_open_search(self) -> None:
        from gimmethatdata.tui.screens.search import SearchScreen

        self.push_screen(SearchScreen(out_root=self.out_root))

    def action_open_sitemap(self) -> None:
        from gimmethatdata.tui.screens.sitemap import LiveSitemapScreen

        domain_dir = _guess_domain_dir(self.out_root)
        if domain_dir is None:
            self.notify("No `_site.sqlite` found anywhere under out_root yet.", title="Sitemap")
            return
        self.push_screen(LiveSitemapScreen(domain_dir=domain_dir))

    def action_open_diff(self) -> None:
        from gimmethatdata.tui.screens.diff import DiffScreen

        self.push_screen(DiffScreen())

    def action_open_settings(self) -> None:
        from gimmethatdata.tui.screens.settings import SettingsScreen

        self.push_screen(SettingsScreen())

    def action_open_instagram(self) -> None:
        from gimmethatdata.tui.screens.instagram import IGAccountsScreen

        self.push_screen(IGAccountsScreen(out_root=self.out_root))

    def action_help(self) -> None:
        self.notify(
            "n: new · s: search · m: sitemap · d: diff · i: instagram · ,: settings · q: quit",
            title="Help",
        )


def _guess_domain_dir(out_root: Path) -> Path | None:
    """Pick the first directory under out_root that has a `_site.sqlite`."""
    if not out_root.exists():
        return None
    for path in out_root.rglob("_site.sqlite"):
        return path.parent
    return None


def run_tui(out_root: Path = Path("out")) -> None:
    GimmeApp(out_root=out_root).run()
