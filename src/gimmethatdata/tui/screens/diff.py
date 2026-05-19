"""Two-pane diff view between two snapshot directories."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, RichLog, Static

from gimmethatdata.export.diff import PageChange, SnapshotDiff, compute_diff


class DiffScreen(Screen[None]):
    """Pick a before + after dir, compute, then explore the diff per page."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("q", "app.pop_screen", "Back"),
        Binding("enter", "compute", "Compute"),
    ]

    def __init__(
        self,
        *,
        before: Path | None = None,
        after: Path | None = None,
    ) -> None:
        super().__init__()
        self.before = before
        self.after = after
        self._diff: SnapshotDiff | None = None
        self._changed: list[PageChange] = []
        self._added_urls: list[str] = []
        self._removed_urls: list[str] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Vertical(
            Static("[b]Diff[/b] · enter two snapshot folders, press Enter"),
            Input(
                placeholder="before path (older snapshot)",
                id="before-input",
                value=str(self.before) if self.before else "",
            ),
            Input(
                placeholder="after path (newer snapshot)",
                id="after-input",
                value=str(self.after) if self.after else "",
            ),
            Static("", id="summary"),
            Horizontal(
                DataTable(id="rows"),
                RichLog(id="patch", highlight=True, markup=False, max_lines=2000, wrap=True),
            ),
        )
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#rows", DataTable)
        table.cursor_type = "row"
        table.add_columns("Kind", "URL")
        if self.before is not None and self.after is not None:
            self.action_compute()

    def action_compute(self) -> None:
        before = Path(self.query_one("#before-input", Input).value.strip() or ".")
        after = Path(self.query_one("#after-input", Input).value.strip() or ".")
        if not before.exists() or not after.exists():
            self.query_one("#summary", Static).update("[red]both paths must exist[/]")
            return
        self._diff = compute_diff(before, after)
        summary = self._diff.summary()
        self.query_one("#summary", Static).update(
            f"added={summary['added']}  removed={summary['removed']}  "
            f"changed={summary['changed']}  unchanged={summary['unchanged']}"
        )
        self._changed = self._diff.changed
        self._added_urls = [p.url for p in self._diff.added]
        self._removed_urls = [p.url for p in self._diff.removed]
        table = self.query_one("#rows", DataTable)
        table.clear()
        for url in self._added_urls:
            table.add_row("+ added", url)
        for url in self._removed_urls:
            table.add_row("- removed", url)
        for change in self._changed:
            table.add_row("~ changed", change.url)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if self._diff is None:
            return
        row = event.cursor_row
        added_n = len(self._added_urls)
        removed_n = len(self._removed_urls)
        patch_log = self.query_one("#patch", RichLog)
        patch_log.clear()
        if row < added_n:
            patch_log.write(f"+ added · {self._added_urls[row]}\n(no before content)")
            return
        if row < added_n + removed_n:
            patch_log.write(f"- removed · {self._removed_urls[row - added_n]}\n(no after content)")
            return
        idx = row - added_n - removed_n
        if idx >= len(self._changed):
            return
        change = self._changed[idx]
        patch_log.write(change.unified_diff or "(content shifted; sha changed)")
