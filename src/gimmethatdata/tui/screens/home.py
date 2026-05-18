"""Home screen: list recent jobs from the ledger."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from gimmethatdata.persist.ledger import Ledger


class HomeScreen(Screen[None]):
    """Lists recent jobs; Enter opens the inspector for the selected job."""

    BINDINGS = [
        Binding("n", "new_job", "New job"),
        Binding("r", "refresh", "Refresh"),
        Binding("enter", "inspect", "Inspect"),
        Binding("escape", "app.pop_screen", "Back"),
    ]

    def __init__(self, *, out_root: Path) -> None:
        super().__init__()
        self.out_root = out_root
        self._jobs: list[dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Vertical(
            Static("[b]Recent jobs[/b]  ([dim]n=new · r=refresh · enter=inspect[/])", id="jobs-header"),
            DataTable(id="jobs-table"),
        )
        yield Footer()

    async def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.cursor_type = "row"
        table.add_columns("Job ID", "Kind", "Status", "Started")
        await self._refresh()

    async def _refresh(self) -> None:
        ledger_path = self.out_root / "_jobs.sqlite"
        table = self.query_one(DataTable)
        table.clear()
        self._jobs = []
        if not ledger_path.exists():
            table.add_row("—", "no ledger yet", "", "")
            return
        ledger = Ledger(ledger_path)
        await ledger.open()
        try:
            self._jobs = await ledger.list_jobs()
        finally:
            await ledger.close()
        if not self._jobs:
            table.add_row("—", "no jobs yet", "", "")
            return
        for job in self._jobs:
            table.add_row(
                job["id"],
                job["kind"],
                job["status"],
                job.get("started_at", "")[:19].replace("T", " "),
            )

    async def action_refresh(self) -> None:
        await self._refresh()

    def action_new_job(self) -> None:
        from gimmethatdata.tui.screens.new_job import NewJobScreen

        self.app.push_screen(NewJobScreen(out_root=self.out_root))

    def action_inspect(self) -> None:
        table = self.query_one(DataTable)
        if not self._jobs:
            return
        cursor = table.cursor_row
        if cursor < 0 or cursor >= len(self._jobs):
            return
        from gimmethatdata.tui.screens.inspector import InspectorScreen

        job = self._jobs[cursor]
        self.app.push_screen(InspectorScreen(out_root=self.out_root, job_id=job["id"]))
