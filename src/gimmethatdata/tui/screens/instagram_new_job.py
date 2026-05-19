"""Start a new Instagram archive job from the TUI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Checkbox, Footer, Header, Input, RichLog, Static
from textual.worker import Worker, WorkerState

from gimmethatdata.tui import log_bridge


class IGNewJobScreen(Screen[None]):
    """Form for one archive run, streams events into a RichLog."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("ctrl+s", "submit", "Submit"),
    ]

    def __init__(self, *, out_root: Path) -> None:
        super().__init__()
        self.out_root = out_root
        self._sink = log_bridge.TUILogSink()
        self._worker: Worker[None] | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Vertical(
            Static("[b]New Instagram job[/b]  [dim]· ctrl+s to start · esc to cancel[/]"),
            Static("Handle (or comma-separated for multi)"),
            Input(placeholder="draftsbyuday", id="handle"),
            Static("Session file (preferred over password)"),
            Input(
                placeholder=".ignore/ig-session",
                id="session-file",
                value=".ignore/ig-session",
            ),
            Static("Or login user (will prompt-via-CLI for password)"),
            Input(placeholder="(blank to stay anonymous)", id="login-user"),
            Horizontal(
                Checkbox("Posts", id="opt-posts", value=True),
                Checkbox("Reels", id="opt-reels", value=True),
                Checkbox("Highlights", id="opt-highlights"),
                Checkbox("Stories", id="opt-stories"),
                Checkbox("Tagged", id="opt-tagged"),
            ),
            Horizontal(
                Checkbox("Comments", id="opt-comments", value=True),
                Checkbox("Likers", id="opt-likers"),
                Checkbox("Comment replies", id="opt-replies"),
                Checkbox("Enrich locations", id="opt-locations"),
                Checkbox("OCR images", id="opt-ocr"),
            ),
            Horizontal(
                Checkbox("Engagement report", id="opt-analytics", value=True),
                Checkbox("Contact sheet", id="opt-sheet"),
                Checkbox("PDF export", id="opt-pdf"),
                Checkbox("Resume (skip dl'd)", id="opt-resume", value=True),
            ),
            Static("Limit (cap posts per profile, blank for all)"),
            Input(placeholder="25", id="limit"),
            Static("Since YYYY-MM-DD (skip older posts, blank for all)"),
            Input(placeholder="", id="since"),
            Horizontal(
                Button("Start (Ctrl+S)", id="submit-btn", variant="primary"),
                Button("Back (Esc)", id="cancel-btn"),
                Static("", id="job-status"),
            ),
            RichLog(id="events", highlight=True, markup=True, max_lines=2000, wrap=True),
        )
        yield Footer()

    def on_mount(self) -> None:
        log_bridge.install(self._sink, level="INFO")
        self.set_interval(0.25, self._drain_sink)

    def on_unmount(self) -> None:
        log_bridge.restore()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "submit-btn":
            self.action_submit()
        elif event.button.id == "cancel-btn":
            self.app.pop_screen()

    def action_submit(self) -> None:
        if self._worker is not None and self._worker.state == WorkerState.RUNNING:
            self.query_one("#job-status", Static).update("[yellow]already running[/]")
            return
        handle_raw = self.query_one("#handle", Input).value.strip()
        if not handle_raw:
            self.query_one("#job-status", Static).update("[red]handle required[/]")
            return
        handles = [h.strip().lstrip("@") for h in handle_raw.split(",") if h.strip()]
        session_raw = self.query_one("#session-file", Input).value.strip()
        session_file = Path(session_raw) if session_raw else None
        login_user_raw = self.query_one("#login-user", Input).value.strip()
        login_user = login_user_raw or None
        limit_raw = self.query_one("#limit", Input).value.strip()
        limit = int(limit_raw) if limit_raw.isdigit() else None
        since_raw = self.query_one("#since", Input).value.strip()
        since = since_raw or None

        config = {
            "handles": handles,
            "out_root": self.out_root,
            "session_file": session_file,
            "login_user": login_user,
            "limit": limit,
            "since": since,
            "fetch_posts": self._cb("opt-posts"),
            "fetch_reels": self._cb("opt-reels"),
            "fetch_highlights": self._cb("opt-highlights"),
            "fetch_stories": self._cb("opt-stories"),
            "fetch_tagged": self._cb("opt-tagged"),
            "fetch_comments": self._cb("opt-comments"),
            "fetch_likers": self._cb("opt-likers"),
            "fetch_replies": self._cb("opt-replies"),
            "enrich_locations": self._cb("opt-locations"),
            "ocr_images": self._cb("opt-ocr"),
            "analytics": self._cb("opt-analytics"),
            "contact_sheet": self._cb("opt-sheet"),
            "pdf": self._cb("opt-pdf"),
            "resume": self._cb("opt-resume"),
        }
        self.query_one("#job-status", Static).update(
            f"[cyan]running on {len(handles)} account(s)…[/]"
        )
        self._worker = self.run_worker(
            self._do_job(config), exclusive=True, name="ig-archive"
        )

    def _cb(self, widget_id: str) -> bool:
        return bool(self.query_one(f"#{widget_id}", Checkbox).value)

    async def _do_job(self, config: dict[str, Any]) -> None:
        from datetime import UTC, datetime

        from gimmethatdata.instagram import (
            IGDownloadOptions,
            IGLoginError,
            InstagramClient,
            analyze_engagement,
            write_contact_sheet,
            write_engagement_report,
        )
        from gimmethatdata.instagram.comments import analyze as analyze_comments
        from gimmethatdata.instagram.comments import write_report as write_comments_report

        status = self.query_one("#job-status", Static)
        log = self.query_one("#events", RichLog)

        try:
            session_file: Path | None = config["session_file"]
            if session_file is not None and session_file.exists():
                client = InstagramClient.from_session_file(
                    username=config["login_user"] or config["handles"][0],
                    session_file=session_file,
                )
                log.write(f"[cyan]session loaded[/] from {session_file}")
            elif config["login_user"] is not None:
                status.update(
                    "[red]password login from the TUI not supported — use --session-file from CLI[/]"
                )
                return
            else:
                client = InstagramClient.anonymous()
                log.write("[yellow]anonymous client — most endpoints will 403[/]")
        except IGLoginError as exc:
            status.update(f"[red]login failed:[/] {exc}")
            return

        since_dt = None
        if config["since"]:
            try:
                since_dt = datetime.fromisoformat(config["since"]).replace(tzinfo=UTC)
            except ValueError:
                log.write(f"[yellow]invalid --since '{config['since']}' (ignored)[/]")

        options = IGDownloadOptions(
            fetch_posts=config["fetch_posts"],
            fetch_reels=config["fetch_reels"],
            fetch_highlights=config["fetch_highlights"],
            fetch_stories=config["fetch_stories"],
            fetch_tagged=config["fetch_tagged"],
            fetch_comments=config["fetch_comments"] and client.logged_in_as is not None,
            fetch_likers=config["fetch_likers"] and client.logged_in_as is not None,
            fetch_comment_replies=config["fetch_replies"],
            enrich_locations=config["enrich_locations"],
            ocr_images=config["ocr_images"],
            download_images=True,
            limit=config["limit"],
            since=since_dt,
            resume=config["resume"],
        )

        def progress(event: str, payload: dict[str, Any]) -> None:
            log.write(f"[dim]{event}[/] {payload}")

        for handle in config["handles"]:
            log.write(f"[bold]downloading[/] @{handle}")
            try:
                report = await self._download_one(
                    client, handle, options, progress, config["out_root"]
                )
            except RuntimeError as exc:
                log.write(f"[red]{handle}:[/] {exc}")
                continue
            log.write(
                f"[green]done @{handle}[/] · posts={report.posts} reels={report.reels} "
                f"tagged={report.tagged} comments={report.comments_collected}"
            )
            profile_root = config["out_root"] / "instagram" / handle
            if config["analytics"]:
                analyze_comments_obj = analyze_comments(profile_root)
                write_comments_report(analyze_comments_obj)
                engagement = analyze_engagement(profile_root)
                write_engagement_report(engagement)
                log.write(f"[green]reports written for @{handle}[/]")
            if config["contact_sheet"]:
                sheet = write_contact_sheet(profile_root)
                log.write(f"[green]contact sheet:[/] {sheet}")
            if config["pdf"]:
                from gimmethatdata.export.pdf import export_to_pdf

                pdf_path = profile_root / f"{handle}.pdf"
                await export_to_pdf(profile_root, out=pdf_path, title=f"@{handle} archive")
                log.write(f"[green]PDF:[/] {pdf_path}")

        status.update("[bold green]all jobs finished[/]")

    async def _download_one(
        self,
        client: Any,
        handle: str,
        options: Any,
        progress_cb: Any,
        out_root: Path,
    ) -> Any:
        import asyncio

        from gimmethatdata.instagram import download_profile

        return await asyncio.to_thread(
            download_profile,
            client,
            handle,
            out_root=out_root,
            options=options,
            on_progress=progress_cb,
        )

    def _drain_sink(self) -> None:
        lines = self._sink.pop_all()
        if not lines:
            return
        log = self.query_one("#events", RichLog)
        for line in lines:
            log.write(line)
