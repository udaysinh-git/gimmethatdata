"""Live sitemap tree — watches `_site.sqlite` and refreshes a tree widget."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static, Tree
from textual.widgets.tree import TreeNode

from gimmethatdata.crawl.frontier import Frontier

_STATUS_BADGES = {
    "done": "✓",
    "failed": "✗",
    "skipped": "↷",
    "pending": "…",
    "in_progress": "▶",
}


class LiveSitemapScreen(Screen[None]):
    """Refreshes a parent→child tree from `<domain_dir>/_site.sqlite` every tick."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("q", "app.pop_screen", "Back"),
        Binding("r", "refresh_now", "Refresh"),
    ]

    def __init__(
        self,
        *,
        domain_dir: Path,
        refresh_seconds: float = 2.0,
    ) -> None:
        super().__init__()
        self.domain_dir = domain_dir
        self.refresh_seconds = refresh_seconds

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Vertical(
            Static(f"[b]Live sitemap[/b] · {self.domain_dir}"),
            Static("", id="counts"),
            Tree("(loading)", id="tree"),
        )
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(self.refresh_seconds, self._refresh)
        self.run_worker(self._refresh(), exclusive=True, name="sitemap-refresh-initial")

    async def action_refresh_now(self) -> None:
        await self._refresh()

    async def _refresh(self) -> None:
        nodes = await self._load_nodes()
        counts = _summarize(nodes)
        self.query_one("#counts", Static).update(_render_counts(counts))
        tree = self.query_one("#tree", Tree)
        tree.clear()
        tree.root.expand()
        tree.root.label = f"{self.domain_dir.name} ({len(nodes)} nodes)"
        _build_tree(tree.root, nodes)

    async def _load_nodes(self) -> list[dict[str, Any]]:
        site_db = self.domain_dir / "_site.sqlite"
        if not site_db.exists():
            return []
        frontier = Frontier(site_db)
        await frontier.open()
        try:
            return [dict(node) for node in await frontier.dump_all()]
        finally:
            await frontier.close()


def _summarize(nodes: list[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for node in nodes:
        out[str(node["status"])] += 1
    return dict(out)


def _render_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "[dim]waiting for crawl to start…[/]"
    parts = [f"{status}={n}" for status, n in sorted(counts.items())]
    return "  ".join(parts)


def _build_tree(root: TreeNode[Any], nodes: list[dict[str, Any]]) -> None:
    by_url = {n["canonical_url"]: n for n in nodes}
    children_of: dict[str | None, list[str]] = defaultdict(list)
    for node in nodes:
        children_of[node["parent_url"]].append(node["canonical_url"])

    seeds = sorted(children_of.get(None, []))
    if not seeds:
        return

    visited: set[str] = set()

    def add(parent: TreeNode[Any], url: str) -> None:
        if url in visited:
            parent.add_leaf(f"↻ {_short(url)}")
            return
        visited.add(url)
        node = by_url.get(url)
        badge = _STATUS_BADGES.get(str(node["status"]) if node else "", "?")
        label = f"{badge} {_short(url)}"
        kids = sorted(children_of.get(url, []))
        if not kids:
            parent.add_leaf(label)
            return
        branch = parent.add(label, expand=True)
        for child in kids:
            add(branch, child)

    for seed in seeds:
        add(root, seed)


def _short(url: str) -> str:
    return url if len(url) <= 90 else url[:87] + "…"
