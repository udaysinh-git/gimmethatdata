"""Global FTS search across every scraped `content.md` under the out_root."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    MarkdownViewer,
    Static,
)

from gimmethatdata.persist.search import SearchHit, SearchIndex, index_all


class SearchScreen(Screen[None]):
    """Search bar + hit table + preview pane."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("ctrl+r", "reindex", "Rebuild index"),
        Binding("enter", "submit", "Search / preview"),
    ]

    def __init__(self, *, out_root: Path) -> None:
        super().__init__()
        self.out_root = out_root
        self._hits: list[SearchHit] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Vertical(
            Static("[b]Search[/b]  [dim]· enter=search · ctrl+r=reindex · esc=back[/]"),
            Input(placeholder="type a query and press enter", id="query-input"),
            Horizontal(
                Button("Search", id="search-btn", variant="primary"),
                Button("Reindex", id="reindex-btn"),
                Static("", id="status"),
            ),
            Horizontal(
                DataTable(id="hits"),
                MarkdownViewer(id="preview", show_table_of_contents=False),
            ),
        )
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#hits", DataTable)
        table.cursor_type = "row"
        table.add_columns("Title", "Snippet")
        db = self.out_root / "_search.sqlite"
        status = self.query_one("#status", Static)
        if not db.exists():
            status.update("[yellow]no index yet — press Reindex to build[/]")
        else:
            status.update(f"[dim]index: {db.name}[/]")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "search-btn":
            self.action_submit()
        elif event.button.id == "reindex-btn":
            self.action_reindex()

    def action_submit(self) -> None:
        query = self.query_one("#query-input", Input).value.strip()
        if not query:
            return
        db = self.out_root / "_search.sqlite"
        if not db.exists():
            self.query_one("#status", Static).update("[yellow]build the index first[/]")
            return
        with SearchIndex(db) as idx:
            self._hits = idx.search(query, limit=50)
        table = self.query_one("#hits", DataTable)
        table.clear()
        if not self._hits:
            table.add_row("—", "no matches")
            self.query_one("#status", Static).update("[yellow]no matches[/]")
            return
        for hit in self._hits:
            table.add_row(hit.title[:60], _flatten_snippet(hit.snippet)[:80])
        self.query_one("#status", Static).update(f"[green]{len(self._hits)} hits[/]")

    def action_reindex(self) -> None:
        self.query_one("#status", Static).update("[cyan]indexing…[/]")
        self.run_worker(self._do_reindex(), exclusive=True, name="reindex")

    async def _do_reindex(self) -> None:
        count = index_all(self.out_root)
        self.query_one("#status", Static).update(
            f"[green]indexed[/] {count} pages — press Search"
        )

    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.cursor_row < 0 or event.cursor_row >= len(self._hits):
            return
        hit = self._hits[event.cursor_row]
        viewer = self.query_one("#preview", MarkdownViewer)
        content_path = Path(hit.output_dir) / "content.md"
        if content_path.exists():
            await viewer.go(str(content_path))


def _flatten_snippet(snippet: str) -> str:
    return snippet.replace("\n", " ").replace("  ", " ")
