"""Hashtag / location / music discovery screen for Instagram."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, RadioButton, RadioSet, RichLog, Static
from textual.worker import Worker, WorkerState


class IGDiscoveryScreen(Screen[None]):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("ctrl+s", "submit", "Run"),
    ]

    def __init__(self, *, out_root: Path) -> None:
        super().__init__()
        self.out_root = out_root
        self._worker: Worker[None] | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Vertical(
            Static("[b]Instagram discovery[/b]  [dim]· hashtag / location / music[/]"),
            RadioSet(
                RadioButton("Hashtag", id="kind-hashtag", value=True),
                RadioButton("Location (numeric pk)", id="kind-location"),
                RadioButton("Music (numeric track id)", id="kind-music"),
                id="kind",
            ),
            Static("Key (tag, location pk, or track id)"),
            Input(placeholder="travel  /  213385402  /  17841401297713411", id="key"),
            Static("Session file (required for almost all of these)"),
            Input(placeholder=".ignore/ig-session", value=".ignore/ig-session", id="session"),
            Static("Sort (hashtag / location only)"),
            RadioSet(
                RadioButton("Top", id="sort-top", value=True),
                RadioButton("Recent", id="sort-recent"),
                id="sort",
            ),
            Static("Amount"),
            Input(value="25", id="amount"),
            Horizontal(
                Button("Run (Ctrl+S)", id="run-btn", variant="primary"),
                Button("Back (Esc)", id="back-btn"),
                Static("", id="status"),
            ),
            RichLog(id="events", highlight=True, markup=True, max_lines=1000, wrap=True),
        )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "run-btn":
            self.action_submit()
        elif event.button.id == "back-btn":
            self.app.pop_screen()

    def action_submit(self) -> None:
        if self._worker is not None and self._worker.state == WorkerState.RUNNING:
            return
        kind_set = self.query_one("#kind", RadioSet).pressed_button
        kind = (kind_set.id or "kind-hashtag").replace("kind-", "") if kind_set else "hashtag"
        sort_set = self.query_one("#sort", RadioSet).pressed_button
        sort = (sort_set.id or "sort-top").replace("sort-", "") if sort_set else "top"
        key = self.query_one("#key", Input).value.strip()
        session_raw = self.query_one("#session", Input).value.strip()
        session_file = Path(session_raw) if session_raw else None
        amount_raw = self.query_one("#amount", Input).value.strip() or "25"
        try:
            amount = max(1, int(amount_raw))
        except ValueError:
            amount = 25
        if not key:
            self.query_one("#status", Static).update("[red]key required[/]")
            return
        self.query_one("#status", Static).update(f"[cyan]{kind} '{key}' (amount={amount})…[/]")
        self._worker = self.run_worker(
            self._do_run(kind=kind, key=key, sort=sort, amount=amount, session_file=session_file),
            exclusive=True,
            name="ig-discovery",
        )

    async def _do_run(
        self,
        *,
        kind: str,
        key: str,
        sort: str,
        amount: int,
        session_file: Path | None,
    ) -> None:
        import asyncio

        from gimmethatdata.instagram import IGLoginError, InstagramClient
        from gimmethatdata.instagram.discovery import (
            discover_hashtag,
            discover_location,
            discover_music,
        )

        log = self.query_one("#events", RichLog)
        try:
            if session_file is not None and session_file.exists():
                client = InstagramClient.from_session_file(
                    username="discovery", session_file=session_file
                )
            else:
                client = InstagramClient.anonymous()
                log.write("[yellow]anonymous — most endpoints will 403[/]")
        except IGLoginError as exc:
            self.query_one("#status", Static).update(f"[red]{exc}[/]")
            return

        def progress(event: str, payload: dict[str, Any]) -> None:
            if event == "discovery_saved":
                log.write(f"  [green]saved[/] [dim]{payload.get('shortcode')}[/]")

        try:
            if kind == "hashtag":
                report = await asyncio.to_thread(
                    discover_hashtag,
                    client, key, out_root=self.out_root, sort=sort, amount=amount,
                    on_progress=progress,
                )
            elif kind == "location":
                report = await asyncio.to_thread(
                    discover_location,
                    client, int(key), out_root=self.out_root, sort=sort, amount=amount,
                    on_progress=progress,
                )
            else:  # music
                report = await asyncio.to_thread(
                    discover_music,
                    client, int(key), out_root=self.out_root, amount=amount,
                    on_progress=progress,
                )
        except ValueError as exc:
            self.query_one("#status", Static).update(f"[red]bad numeric key:[/] {exc}")
            return
        except Exception as exc:
            self.query_one("#status", Static).update(f"[red]{exc}[/]")
            return

        self.query_one("#status", Static).update(
            f"[green]done[/] saved={report.saved} skipped={report.skipped_existing} "
            f"images={report.images_downloaded} -> {report.target_dir}"
        )
        for err in report.errors[:5]:
            log.write(f"  [yellow]·[/] {err}")
