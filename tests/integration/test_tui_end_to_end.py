"""End-to-end TUI smoke: NewJob → ProgressScreen actually runs a scrape."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from gimmethatdata.tui.app import GimmeApp


@pytest.mark.asyncio
@respx.mock
async def test_tui_runs_scrape_end_to_end(tmp_path: Path, blog_html: str) -> None:
    url = "https://example.com/blog/post-1"
    respx.get(url).mock(
        return_value=httpx.Response(
            200,
            text=blog_html,
            headers={"content-type": "text/html; charset=utf-8"},
        )
    )
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(404, text="")
    )

    app = GimmeApp(out_root=tmp_path)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Home → NewJob
        await pilot.press("n")
        await pilot.pause()
        assert app.screen.__class__.__name__ == "NewJobScreen"

        # Fill the URL field and submit.
        from textual.widgets import Input

        url_input = app.screen.query_one("#url-input", Input)
        url_input.value = url
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()

        assert app.screen.__class__.__name__ == "ProgressScreen"

        # Wait for the worker to finish.
        worker = getattr(app.screen, "_worker", None)
        assert worker is not None
        await worker.wait()
        await pilot.pause(0.4)

        # Output landed on disk
        target = tmp_path / "example.com"
        assert target.exists()
        any_content = list(target.glob("**/content.md"))
        assert any_content, "expected content.md from the scrape"
