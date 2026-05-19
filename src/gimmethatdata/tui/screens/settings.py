"""Edit `gimmethatdata.toml` from inside the TUI.

Loads the project-local config (creating it from defaults if missing), lets you
edit fields, then writes back. Doesn't try to be a full TOML editor — just the
common knobs (concurrency, fetch.timeout_seconds, fetch.user_agent, crawl.*).
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import tomli_w
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Checkbox, Footer, Header, Input, Static

_CONFIG_FILENAME = "gimmethatdata.toml"


class SettingsScreen(Screen[None]):
    """Form-driven editor for the common settings."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("ctrl+s", "save", "Save"),
    ]

    def __init__(self, *, config_path: Path | None = None) -> None:
        super().__init__()
        self.config_path = config_path or (Path.cwd() / _CONFIG_FILENAME)
        self._loaded: dict[str, Any] = {}

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Vertical(
            Static(f"[b]Settings[/b]  ·  editing [dim]{self.config_path}[/]"),
            Static("Concurrency"),
            Input(placeholder="8", id="concurrency"),
            Static("Per-request timeout (seconds)"),
            Input(placeholder="30", id="timeout"),
            Static("User-Agent"),
            Input(placeholder="Mozilla/5.0 …", id="user-agent"),
            Static("Crawl max depth"),
            Input(placeholder="2", id="max-depth"),
            Static("Crawl max pages"),
            Input(placeholder="100", id="max-pages"),
            Horizontal(
                Checkbox("Respect robots.txt by default", id="respect-robots", value=True),
                Checkbox("Verify TLS", id="verify-tls", value=True),
            ),
            Horizontal(
                Button("Save (Ctrl+S)", id="save-btn", variant="primary"),
                Button("Cancel (Esc)", id="cancel-btn"),
                Static("", id="msg"),
            ),
        )
        yield Footer()

    def on_mount(self) -> None:
        self._loaded = _read_config(self.config_path)
        self._populate_inputs(self._loaded)

    def _populate_inputs(self, cfg: dict[str, Any]) -> None:
        concurrency = cfg.get("concurrency", 8)
        fetch = cfg.get("fetch", {}) or {}
        crawl = cfg.get("crawl", {}) or {}
        self.query_one("#concurrency", Input).value = str(concurrency)
        self.query_one("#timeout", Input).value = str(fetch.get("timeout_seconds", 30))
        self.query_one("#user-agent", Input).value = str(fetch.get("user_agent", ""))
        self.query_one("#max-depth", Input).value = str(crawl.get("max_depth", 2))
        self.query_one("#max-pages", Input).value = str(crawl.get("max_pages", 100))
        self.query_one("#respect-robots", Checkbox).value = bool(
            crawl.get("respect_robots", True)
        )
        self.query_one("#verify-tls", Checkbox).value = bool(fetch.get("verify_tls", True))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            self.action_save()
        elif event.button.id == "cancel-btn":
            self.app.pop_screen()

    def action_save(self) -> None:
        try:
            payload = self._collect()
        except ValueError as exc:
            self.query_one("#msg", Static).update(f"[red]{exc}[/]")
            return
        self.config_path.write_bytes(tomli_w.dumps(payload).encode("utf-8"))
        self.query_one("#msg", Static).update(f"[green]wrote {self.config_path}[/]")

    def _collect(self) -> dict[str, Any]:
        try:
            concurrency = int(self.query_one("#concurrency", Input).value or "8")
            timeout = float(self.query_one("#timeout", Input).value or "30")
            max_depth = int(self.query_one("#max-depth", Input).value or "2")
            max_pages = int(self.query_one("#max-pages", Input).value or "100")
        except ValueError as exc:
            raise ValueError(f"numeric field invalid: {exc}") from exc
        return {
            "concurrency": concurrency,
            "fetch": {
                "timeout_seconds": timeout,
                "user_agent": self.query_one("#user-agent", Input).value.strip(),
                "verify_tls": self.query_one("#verify-tls", Checkbox).value,
            },
            "crawl": {
                "max_depth": max_depth,
                "max_pages": max_pages,
                "respect_robots": self.query_one("#respect-robots", Checkbox).value,
            },
        }


def _read_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
