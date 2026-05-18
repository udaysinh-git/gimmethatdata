"""TUI smoke: app constructs and screens import cleanly."""

from __future__ import annotations

from pathlib import Path

import pytest

from gimmethatdata.tui.app import GimmeApp


def test_app_instantiates(tmp_path: Path) -> None:
    app = GimmeApp(out_root=tmp_path)
    assert app.TITLE == "gimmethatdata"
    assert app.out_root == tmp_path
    bindings = {b.key for b in app.BINDINGS}
    assert {"q", "n"}.issubset(bindings)


def test_screens_importable() -> None:
    from gimmethatdata.tui.screens.home import HomeScreen
    from gimmethatdata.tui.screens.inspector import InspectorScreen
    from gimmethatdata.tui.screens.new_job import NewJobScreen
    from gimmethatdata.tui.screens.progress import ProgressScreen

    assert HomeScreen is not None
    assert InspectorScreen is not None
    assert NewJobScreen is not None
    assert ProgressScreen is not None


@pytest.mark.asyncio
async def test_app_pilot_boots(tmp_path: Path) -> None:
    """Drive the app with Textual's pilot to ensure on_mount works end-to-end."""
    app = GimmeApp(out_root=tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.screen.__class__.__name__ == "HomeScreen"
        await pilot.press("q")
