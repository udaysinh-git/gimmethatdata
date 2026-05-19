"""Compare two scraped Instagram profiles side-by-side from the TUI."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, MarkdownViewer, Static


class IGCompareScreen(Screen[None]):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("ctrl+s", "submit", "Compare"),
    ]

    def __init__(self, *, out_root: Path) -> None:
        super().__init__()
        self.out_root = out_root

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Vertical(
            Static("[b]Compare two IG profiles[/b]"),
            Static("Left profile dir"),
            Input(placeholder=str(self.out_root / "instagram" / "userA"), id="left"),
            Static("Right profile dir"),
            Input(placeholder=str(self.out_root / "instagram" / "userB"), id="right"),
            Horizontal(
                Button("Compare (Ctrl+S)", id="run-btn", variant="primary"),
                Button("Back (Esc)", id="back-btn"),
                Static("", id="status"),
            ),
            MarkdownViewer(id="result", show_table_of_contents=False),
        )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "run-btn":
            self.action_submit()
        elif event.button.id == "back-btn":
            self.app.pop_screen()

    def action_submit(self) -> None:
        from gimmethatdata.instagram import compare_profiles, write_compare_report

        left = Path(self.query_one("#left", Input).value.strip())
        right = Path(self.query_one("#right", Input).value.strip())
        if not left.exists() or not right.exists():
            self.query_one("#status", Static).update("[red]both profile dirs must exist[/]")
            return
        try:
            report = compare_profiles(left, right)
            md_path, _ = write_compare_report(report)
        except Exception as exc:
            self.query_one("#status", Static).update(f"[red]{exc}[/]")
            return
        self.query_one("#status", Static).update(
            f"[green]done[/] · jaccard {report.jaccard_commenters:.3f} · "
            f"{len(report.shared_commenters)} shared commenters"
        )
        viewer = self.query_one("#result", MarkdownViewer)
        self.run_worker(viewer.go(str(md_path)), exclusive=True, name="ig-compare-view")
