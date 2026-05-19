"""Instagram TUI: browse archived profiles, posts, comments, reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Markdown,
    MarkdownViewer,
    Static,
    TabbedContent,
    TabPane,
)


class IGAccountsScreen(Screen[None]):
    """Three-pane Instagram browser: accounts > posts > preview.

    - Left: accounts found under `<out_root>/instagram/<user>/`.
    - Middle: posts/reels/tagged for the selected account.
    - Right: tabbed preview (content / comments / engagement report).
    """

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("q", "app.pop_screen", "Back"),
        Binding("r", "refresh", "Refresh"),
        Binding("n", "new_job", "New IG job"),
        Binding("d", "open_discovery", "Discovery"),
        Binding("c", "open_compare", "Compare"),
        Binding("g", "generate_reports", "(re)build reports"),
    ]

    def __init__(self, *, out_root: Path) -> None:
        super().__init__()
        self.out_root = out_root
        self._accounts: list[Path] = []
        self._posts: list[dict[str, Any]] = []
        self._selected_account: Path | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical():
            yield Static(
                "[b]Instagram archive[/b]   "
                "[dim]· n=new · d=discovery · c=compare · g=reports · r=refresh · esc=back[/]",
                id="ig-banner",
            )
            with Horizontal():
                yield DataTable(id="accounts")
                yield DataTable(id="posts")
                with TabbedContent(id="preview-tabs"):
                    with TabPane("Content", id="tab-content"):
                        yield MarkdownViewer(id="preview", show_table_of_contents=False)
                    with TabPane("Comments", id="tab-comments"):
                        yield Markdown("Select a post.", id="preview-comments")
                    with TabPane("Engagement", id="tab-engagement"):
                        yield MarkdownViewer(
                            id="preview-engagement", show_table_of_contents=False
                        )
            with Horizontal():
                yield Button("New job", id="btn-new")
                yield Button("Discovery", id="btn-discovery")
                yield Button("Compare", id="btn-compare")
                yield Button("Rebuild reports", id="btn-reports")
                yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        accounts = self.query_one("#accounts", DataTable)
        accounts.cursor_type = "row"
        accounts.add_columns("@account", "posts", "comments")
        posts = self.query_one("#posts", DataTable)
        posts.cursor_type = "row"
        posts.add_columns("shortcode", "kind", "❤", "💬", "first line")
        self.action_refresh()

    def _ig_root(self) -> Path:
        return self.out_root / "instagram"

    def action_refresh(self) -> None:
        ig_root = self._ig_root()
        accounts_table = self.query_one("#accounts", DataTable)
        accounts_table.clear()
        self._accounts = []
        if not ig_root.exists():
            self.query_one("#status", Static).update(
                "[yellow]no `<out>/instagram/` directory yet — start a job[/]"
            )
            return
        for child in sorted(p for p in ig_root.iterdir() if p.is_dir()):
            if child.name in {"hashtags", "locations", "music"}:
                continue
            counts = _quick_counts(child)
            accounts_table.add_row(
                f"@{child.name}",
                str(counts["posts"] + counts["reels"]),
                str(counts["comments"]),
            )
            self._accounts.append(child)
        if not self._accounts:
            self.query_one("#status", Static).update(
                "[yellow]no profiles archived yet[/]"
            )
        else:
            self.query_one("#status", Static).update(
                f"[dim]{len(self._accounts)} profiles · select one[/]"
            )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        widget = event.control
        if widget.id == "accounts":
            self._on_account_selected(event.cursor_row)
        elif widget.id == "posts":
            self._on_post_selected(event.cursor_row)

    def _on_account_selected(self, row: int) -> None:
        if row < 0 or row >= len(self._accounts):
            return
        account = self._accounts[row]
        self._selected_account = account
        self._populate_posts(account)
        self._load_engagement(account)

    def _populate_posts(self, account: Path) -> None:
        posts_table = self.query_one("#posts", DataTable)
        posts_table.clear()
        self._posts = []
        for kind, subdir in (("post", "posts"), ("reel", "reels"), ("tagged", "tagged")):
            for metadata_path in sorted((account / subdir).rglob("metadata.json")):
                try:
                    meta = json.loads(metadata_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if not isinstance(meta, dict):
                    continue
                first = (meta.get("caption") or "").splitlines()
                snippet = (first[0] if first else "")[:60]
                self._posts.append(
                    {
                        "post_dir": metadata_path.parent,
                        "kind": kind,
                        "shortcode": meta.get("shortcode") or metadata_path.parent.name,
                        "likes": int(meta.get("likes") or 0),
                        "comments": int(meta.get("comments_count") or 0),
                        "first_line": snippet,
                        "taken_at": meta.get("taken_at") or "",
                    }
                )
        self._posts.sort(key=lambda p: p.get("taken_at") or "", reverse=True)
        for post in self._posts:
            posts_table.add_row(
                post["shortcode"],
                post["kind"],
                str(post["likes"]),
                str(post["comments"]),
                post["first_line"],
            )

    def _on_post_selected(self, row: int) -> None:
        if row < 0 or row >= len(self._posts):
            return
        post = self._posts[row]
        post_dir: Path = post["post_dir"]
        content_path = post_dir / "content.md"
        viewer = self.query_one("#preview", MarkdownViewer)
        if content_path.exists():
            self.run_worker(viewer.go(str(content_path)), exclusive=True, name="ig-content")
        comments_widget = self.query_one("#preview-comments", Markdown)
        comments_widget.update(_render_comment_thread(post_dir))

    def _load_engagement(self, account: Path) -> None:
        report_md = account / "_engagement_report.md"
        viewer = self.query_one("#preview-engagement", MarkdownViewer)
        if report_md.exists():
            self.run_worker(viewer.go(str(report_md)), exclusive=True, name="ig-engagement")
        else:
            self.run_worker(
                viewer.document.update(
                    "_No engagement report yet — press `g` or click 'Rebuild reports'._"
                ),
                exclusive=True,
                name="ig-engagement-empty",
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn = event.button.id
        if btn == "btn-new":
            self.action_new_job()
        elif btn == "btn-discovery":
            self.action_open_discovery()
        elif btn == "btn-compare":
            self.action_open_compare()
        elif btn == "btn-reports":
            self.action_generate_reports()

    def action_new_job(self) -> None:
        from gimmethatdata.tui.screens.instagram_new_job import IGNewJobScreen

        self.app.push_screen(IGNewJobScreen(out_root=self.out_root))

    def action_open_discovery(self) -> None:
        from gimmethatdata.tui.screens.instagram_discovery import IGDiscoveryScreen

        self.app.push_screen(IGDiscoveryScreen(out_root=self.out_root))

    def action_open_compare(self) -> None:
        from gimmethatdata.tui.screens.instagram_compare import IGCompareScreen

        self.app.push_screen(IGCompareScreen(out_root=self.out_root))

    def action_generate_reports(self) -> None:
        if self._selected_account is None:
            self.query_one("#status", Static).update(
                "[yellow]select a profile first[/]"
            )
            return
        self.query_one("#status", Static).update("[cyan]rebuilding reports…[/]")
        self.run_worker(
            self._do_reports(self._selected_account), exclusive=True, name="ig-reports"
        )

    async def _do_reports(self, account: Path) -> None:
        from gimmethatdata.instagram import (
            analyze_engagement,
            write_contact_sheet,
            write_engagement_report,
        )
        from gimmethatdata.instagram.comments import (
            analyze as analyze_comments,
        )
        from gimmethatdata.instagram.comments import (
            write_report as write_comments_report,
        )

        analyze_comments_report = analyze_comments(account)
        write_comments_report(analyze_comments_report)
        engagement = analyze_engagement(account)
        write_engagement_report(engagement)
        write_contact_sheet(account)
        self.query_one("#status", Static).update(
            "[green]reports rebuilt[/] · engagement + comments + contact sheet"
        )
        self._load_engagement(account)


def _quick_counts(account: Path) -> dict[str, int]:
    posts = sum(1 for _ in (account / "posts").rglob("metadata.json"))
    reels = sum(1 for _ in (account / "reels").rglob("metadata.json"))
    comments = 0
    for comments_path in account.rglob("comments.json"):
        try:
            payload = json.loads(comments_path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                comments += len(payload)
        except (OSError, json.JSONDecodeError):
            continue
    return {"posts": posts, "reels": reels, "comments": comments}


def _render_comment_thread(post_dir: Path) -> str:
    """Render comments.json as an indented Markdown chat."""
    comments_path = post_dir / "comments.json"
    if not comments_path.exists():
        return "_no comments file_"
    try:
        payload = json.loads(comments_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "_could not parse comments_"
    if not isinstance(payload, list) or not payload:
        return "_no comments_"
    lines: list[str] = [f"### {len(payload)} comments\n"]
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        owner = entry.get("owner", "?")
        text = (entry.get("text") or "").replace("\n", " ")
        likes = entry.get("likes", 0)
        when = (entry.get("created_at") or "")[:19].replace("T", " ")
        lines.append(f"- **@{owner}** · ❤ {likes} · `{when}`")
        lines.append(f"  > {text}")
        for reply in entry.get("replies") or []:
            if not isinstance(reply, dict):
                continue
            r_owner = reply.get("owner", "?")
            r_text = (reply.get("text") or "").replace("\n", " ")
            r_likes = reply.get("likes", 0)
            lines.append(f"    - **@{r_owner}** · ❤ {r_likes}")
            lines.append(f"      > {r_text}")
        lines.append("")
    return "\n".join(lines)
