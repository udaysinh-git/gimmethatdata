"""Inspector screen: browse a job's output tree, preview content.md, export to PDF."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import (
    Button,
    DataTable,
    DirectoryTree,
    Footer,
    Header,
    MarkdownViewer,
    Static,
)
from textual.worker import Worker, WorkerState

from gimmethatdata.persist.ledger import Ledger


class InspectorScreen(Screen[None]):
    """Show pages of a job + preview content.md + offer PDF export."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("q", "app.pop_screen", "Back"),
        Binding("e", "export_pdf", "Export PDF"),
    ]

    def __init__(self, *, out_root: Path, job_id: str) -> None:
        super().__init__()
        self.out_root = out_root
        self.job_id = job_id
        self._pages: list[dict[str, str]] = []
        self._export_worker: Worker[None] | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Vertical(
            Static(f"[b]Inspector[/b] · job={self.job_id}"),
            Horizontal(
                DataTable(id="pages"),
                MarkdownViewer(id="preview", show_table_of_contents=False),
            ),
            Static("[dim]Enter=preview · e=export PDF[/]", id="hint"),
            Horizontal(
                Button("Export PDF (e)", id="export-btn", variant="primary"),
                Static("", id="export-status"),
            ),
            DirectoryTree(self.out_root, id="tree"),
        )
        yield Footer()

    async def on_mount(self) -> None:
        ledger_path = self.out_root / "_jobs.sqlite"
        table = self.query_one("#pages", DataTable)
        table.cursor_type = "row"
        table.add_columns("URL", "Tier", "Updated")
        if not ledger_path.exists():
            table.add_row("—", "no ledger", "")
            return
        ledger = Ledger(ledger_path)
        await ledger.open()
        try:
            self._pages = [
                {k: str(v) for k, v in p.items()}
                for p in await ledger.list_done_pages(self.job_id)
            ]
        finally:
            await ledger.close()
        if not self._pages:
            table.add_row("—", "no pages yet", "")
            return
        for page in self._pages:
            table.add_row(
                page["canonical_url"],
                page.get("tier", ""),
                page.get("updated_at", "")[:19].replace("T", " "),
            )

    async def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.cursor_row < 0 or event.cursor_row >= len(self._pages):
            return
        page = self._pages[event.cursor_row]
        output_dir = page.get("output_dir")
        if not output_dir:
            return
        content_path = Path(output_dir) / "content.md"
        viewer = self.query_one("#preview", MarkdownViewer)
        if content_path.exists():
            await viewer.go(str(content_path))
        else:
            await viewer.document.update(f"# Missing\n\n`{content_path}` not found.")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "export-btn":
            self.action_export_pdf()

    def _domain_root(self) -> Path | None:
        """Best guess at the domain root holding all this job's pages."""
        if not self._pages:
            return None
        first_dir = self._pages[0].get("output_dir")
        if not first_dir:
            return None
        return Path(first_dir).parent

    def action_export_pdf(self) -> None:
        if self._export_worker is not None and self._export_worker.state == WorkerState.RUNNING:
            self.query_one("#export-status", Static).update("[yellow]already exporting…[/]")
            return
        source = self._domain_root()
        if source is None:
            self.query_one("#export-status", Static).update("[red]no pages to export[/]")
            return
        out_pdf = source / f"export-{self.job_id}.pdf"
        self.query_one("#export-status", Static).update(
            f"[cyan]exporting {len(self._pages)} pages → {out_pdf}…[/]"
        )
        self._export_worker = self.run_worker(
            self._do_export(source, out_pdf), exclusive=True, name="pdf-export"
        )

    async def _do_export(self, source: Path, out_pdf: Path) -> None:
        from gimmethatdata.export.pdf import export_to_pdf

        status = self.query_one("#export-status", Static)
        try:
            result = await export_to_pdf(source, out=out_pdf, title=None)
        except Exception as exc:
            status.update(f"[red]export failed:[/] {exc}")
            return
        size_kb = result.stat().st_size // 1024
        status.update(f"[green]wrote[/] {result} ({size_kb} KB)")
