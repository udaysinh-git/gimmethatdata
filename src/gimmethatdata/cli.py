"""Typer CLI entry point for gimmethatdata."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from gimmethatdata import __version__
from gimmethatdata.core.models import AssetKind
from gimmethatdata.logging_setup import configure_logging

app = typer.Typer(
    name="gimmethatdata",
    help="All-in-one async web scraper with Textual TUI.",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="rich",
)
console = Console()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"gimmethatdata [bold cyan]{__version__}[/]")
        raise typer.Exit()


@app.callback()
def _root(
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Verbose logging.")
    ] = False,
    quiet: Annotated[
        bool, typer.Option("--quiet", "-q", help="Suppress non-error output.")
    ] = False,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show version and exit.",
        ),
    ] = False,
) -> None:
    """Configure global logging before any subcommand runs."""
    level = "DEBUG" if verbose else "ERROR" if quiet else "INFO"
    configure_logging(level=level)


def _parse_urls_file(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [
        ln.strip()
        for ln in lines
        if ln.strip() and not ln.strip().startswith("#")
    ]


@app.command()
def scrape(
    urls: Annotated[
        list[str] | None,
        typer.Argument(help="One or more URLs to scrape (omit if using --urls-file)."),
    ] = None,
    urls_file: Annotated[
        Path | None,
        typer.Option(
            "--urls-file",
            help="Read URLs from a file (one per line, # comments allowed).",
        ),
    ] = None,
    job_id: Annotated[
        str | None,
        typer.Option("--job-id", help="Job id (default: timestamped). Resumable."),
    ] = None,
    out: Annotated[
        Path,
        typer.Option("--out", "-o", help="Output root directory."),
    ] = Path("out"),
    download_images: Annotated[
        bool, typer.Option("--download-images", help="Download discovered images.")
    ] = False,
    download_videos: Annotated[
        bool, typer.Option("--download-videos", help="Download discovered videos.")
    ] = False,
    keep_html: Annotated[
        bool, typer.Option("--keep-html", help="Persist raw HTML alongside content.md.")
    ] = False,
    timeout: Annotated[
        float, typer.Option("--timeout", help="Per-request timeout in seconds.")
    ] = 30.0,
    tier: Annotated[
        str,
        typer.Option(
            "--tier",
            help="Fetch tier: auto (escalator), 1 (httpx), 2 (curl_cffi), 3 (playwright), 4 (flaresolverr).",
        ),
    ] = "auto",
    proxy: Annotated[
        str | None,
        typer.Option("--proxy", help="Single proxy URL (http://user:pass@host:port)."),
    ] = None,
    rate_limit: Annotated[
        float,
        typer.Option("--rate-limit", help="Per-domain requests per second."),
    ] = 2.0,
    download_audio: Annotated[
        bool, typer.Option("--download-audio", help="Download discovered audio files.")
    ] = False,
    asset_types: Annotated[
        str | None,
        typer.Option(
            "--asset-types",
            help="CSV of asset kinds to download (image,video,audio). Overrides --download-* flags.",
        ),
    ] = None,
    max_asset_mb: Annotated[
        int, typer.Option("--max-asset-mb", help="Per-asset size cap in MB.")
    ] = 50,
    max_total_mb: Annotated[
        int, typer.Option("--max-total-mb", help="Per-job total asset size cap in MB.")
    ] = 2048,
    respect_robots: Annotated[
        bool,
        typer.Option(
            "--respect-robots/--ignore-robots",
            help="Honor robots.txt (default on).",
        ),
    ] = True,
    preset: Annotated[
        str,
        typer.Option(
            "--preset",
            help="Output preset: vanilla, obsidian, logseq.",
        ),
    ] = "vanilla",
    ocr: Annotated[
        bool,
        typer.Option(
            "--ocr",
            help="Run OCR on downloaded images and append to content.md.",
        ),
    ] = False,
) -> None:
    """Scrape one or more pages."""
    combined_urls: list[str] = list(urls or [])
    if urls_file is not None:
        combined_urls.extend(_parse_urls_file(urls_file))
    if not combined_urls:
        raise typer.BadParameter("No URLs supplied (pass arguments or --urls-file).")

    asyncio.run(
        _run_scrape(
            urls=combined_urls,
            out=out,
            job_id=job_id,
            download_images=download_images,
            download_videos=download_videos,
            download_audio=download_audio,
            asset_types_csv=asset_types,
            max_asset_mb=max_asset_mb,
            max_total_mb=max_total_mb,
            respect_robots=respect_robots,
            keep_html=keep_html,
            timeout=timeout,
            tier=tier,
            proxy=proxy,
            rate_limit=rate_limit,
            preset_name=preset,
            ocr=ocr,
        )
    )


def _resolve_asset_types(
    *,
    csv: str | None,
    images: bool,
    videos: bool,
    audio: bool,
) -> frozenset[AssetKind]:
    if csv is not None:
        kinds: set[AssetKind] = set()
        for raw in csv.split(","):
            key = raw.strip().lower()
            if not key:
                continue
            try:
                kinds.add(AssetKind(key))
            except ValueError as exc:
                raise typer.BadParameter(f"unknown asset kind: {key}") from exc
        return frozenset(kinds)
    selected: set[AssetKind] = set()
    if images:
        selected.add(AssetKind.IMAGE)
    if videos:
        selected.add(AssetKind.VIDEO)
    if audio:
        selected.add(AssetKind.AUDIO)
    return frozenset(selected)


async def _run_scrape(
    *,
    urls: list[str],
    out: Path,
    job_id: str | None,
    download_images: bool,
    download_videos: bool,
    download_audio: bool,
    asset_types_csv: str | None,
    max_asset_mb: int,
    max_total_mb: int,
    respect_robots: bool,
    keep_html: bool,
    timeout: float,  # noqa: ASYNC109 — request timeout, not a co-routine cancel deadline
    tier: str,
    proxy: str | None,
    rate_limit: float,
    preset_name: str,
    ocr: bool,
) -> None:
    from gimmethatdata.core.pipeline import ScrapeOptions
    from gimmethatdata.core.runner import ScrapeJobSpec
    from gimmethatdata.parse.plugins import discover_extractors
    from gimmethatdata.parse.presets import Preset

    asset_types = _resolve_asset_types(
        csv=asset_types_csv,
        images=download_images,
        videos=download_videos,
        audio=download_audio,
    )
    if ocr and AssetKind.IMAGE not in asset_types:
        asset_types = frozenset(asset_types | {AssetKind.IMAGE})
    try:
        preset = Preset(preset_name)
    except ValueError as exc:
        raise typer.BadParameter(f"unknown preset: {preset_name}") from exc
    options = ScrapeOptions(
        asset_types=asset_types,
        max_asset_mb=max_asset_mb,
        max_total_mb=max_total_mb,
        keep_html=keep_html,
        respect_robots=respect_robots,
        download_video_embeds=download_videos,
        preset=preset,
        enable_ocr=ocr,
        extractors=discover_extractors(),
    )
    spec = ScrapeJobSpec(
        urls=urls,
        out=out,
        options=options,
        job_id=job_id,
        timeout=timeout,
        tier=tier,
        proxy=proxy,
        rate_limit=rate_limit,
    )
    await _run_with_cli_progress(spec=spec)


async def _run_with_cli_progress(*, spec: object) -> None:
    """Drive the runner with a Rich progress bar + console.print event callback."""
    from rich.progress import (
        BarColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
    )

    from gimmethatdata.core.runner import JobEvent, ScrapeJobSpec, run_scrape_job

    if not isinstance(spec, ScrapeJobSpec):
        raise TypeError("expected ScrapeJobSpec")

    state: dict[str, int] = {"total": len(spec.urls), "done": 0}

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}[/]"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task("scraping", total=state["total"])

        def on_event(event: JobEvent) -> None:
            if event.kind == "started":
                total = event.extra.get("total", state["total"])
                state["total"] = int(total)
                progress.update(task_id, total=state["total"])
            elif event.kind == "page_done":
                state["done"] += 1
                console.print(
                    f"[green]done[/] {event.url} -> [dim]{event.output_dir}[/] "
                    f"(tier={event.tier})"
                )
                progress.update(task_id, completed=state["done"])
            elif event.kind == "page_failed":
                state["done"] += 1
                console.print(f"[red]fail[/] {event.url}: {event.error}")
                progress.update(task_id, completed=state["done"])
            elif event.kind == "finished":
                summary = ", ".join(f"{k}={v}" for k, v in (event.summary or {}).items())
                console.print(f"[bold]job {event.job_id} finished[/] · {summary}")

        try:
            await run_scrape_job(spec, on_event=on_event)
        except KeyboardInterrupt:
            console.print(
                "[yellow]interrupted[/] — state preserved, run `resume <job-id>` to continue."
            )
            raise


@app.command()
def crawl(
    url: Annotated[str, typer.Argument(help="Seed URL to crawl from.")],
    out: Annotated[
        Path,
        typer.Option("--out", "-o", help="Output root directory."),
    ] = Path("out"),
    depth: Annotated[int, typer.Option("--depth", "-d", help="Max crawl depth.")] = 2,
    max_pages: Annotated[
        int, typer.Option("--max-pages", help="Hard cap on pages to fetch.")
    ] = 100,
    scope: Annotated[
        str,
        typer.Option(
            "--scope",
            help="Scope: same-domain (default), same-host, allowlist (requires --allow).",
        ),
    ] = "same-domain",
    allow: Annotated[
        list[str] | None,
        typer.Option("--allow", help="Glob pattern URLs must match (allowlist mode)."),
    ] = None,
    deny: Annotated[
        list[str] | None,
        typer.Option("--deny", help="Glob pattern URLs must NOT match."),
    ] = None,
    use_sitemap: Annotated[
        bool,
        typer.Option("--use-sitemap/--no-sitemap", help="Seed frontier from sitemap.xml."),
    ] = True,
    tier: Annotated[str, typer.Option("--tier")] = "auto",
    proxy: Annotated[str | None, typer.Option("--proxy")] = None,
    rate_limit: Annotated[float, typer.Option("--rate-limit")] = 1.0,
    timeout: Annotated[float, typer.Option("--timeout")] = 30.0,
    respect_robots: Annotated[
        bool, typer.Option("--respect-robots/--ignore-robots")
    ] = True,
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Skip confirmation for heavy crawls.")
    ] = False,
) -> None:
    """Crawl an entire site within scope."""
    if max_pages > 1000 and not yes:
        confirm = typer.confirm(
            f"[heavy] About to crawl up to {max_pages} pages. Continue?",
            default=False,
        )
        if not confirm:
            raise typer.Exit(code=1)
    asyncio.run(
        _run_crawl(
            seed_url=url,
            out=out,
            depth=depth,
            max_pages=max_pages,
            scope=scope,
            allow=allow or [],
            deny=deny or [],
            use_sitemap=use_sitemap,
            tier=tier,
            proxy=proxy,
            rate_limit=rate_limit,
            timeout=timeout,
            respect_robots=respect_robots,
        )
    )


async def _run_crawl(
    *,
    seed_url: str,
    out: Path,
    depth: int,
    max_pages: int,
    scope: str,
    allow: list[str],
    deny: list[str],
    use_sitemap: bool,
    tier: str,
    proxy: str | None,
    rate_limit: float,
    timeout: float,  # noqa: ASYNC109
    respect_robots: bool,
) -> None:
    from gimmethatdata.core.pipeline import ScrapeOptions
    from gimmethatdata.core.runner import CrawlJobSpec, run_crawl_job
    from gimmethatdata.crawl.frontier import ScopeMode

    try:
        scope_mode = ScopeMode(scope)
    except ValueError as exc:
        raise typer.BadParameter(f"unknown scope: {scope}") from exc
    spec = CrawlJobSpec(
        seed_url=seed_url,
        out=out,
        depth=depth,
        max_pages=max_pages,
        scope=scope_mode,
        allow=allow,
        deny=deny,
        use_sitemap=use_sitemap,
        options=ScrapeOptions(respect_robots=respect_robots),
        timeout=timeout,
        tier=tier,
        proxy=proxy,
        rate_limit=rate_limit,
    )
    report = await run_crawl_job(spec)
    console.print(
        f"[bold]crawl done[/] · fetched={report.fetched} "
        f"failed={report.failed} skipped={report.skipped}"
    )


@app.command()
def tui(
    out: Annotated[
        Path,
        typer.Option("--out", "-o", help="Output root directory (where _jobs.sqlite lives)."),
    ] = Path("out"),
) -> None:
    """Launch the Textual TUI."""
    from gimmethatdata.tui.app import run_tui

    run_tui(out_root=out)


@app.command()
def resume(
    job_id: Annotated[str, typer.Argument(help="Job id to resume.")],
    out: Annotated[
        Path,
        typer.Option("--out", "-o", help="Output root directory holding _jobs.sqlite."),
    ] = Path("out"),
    retry_failed: Annotated[
        bool, typer.Option("--retry-failed", help="Retry pages that previously failed.")
    ] = False,
    timeout: Annotated[
        float, typer.Option("--timeout", help="Per-request timeout in seconds.")
    ] = 30.0,
    tier: Annotated[str, typer.Option("--tier")] = "auto",
    proxy: Annotated[str | None, typer.Option("--proxy")] = None,
    rate_limit: Annotated[float, typer.Option("--rate-limit")] = 2.0,
    respect_robots: Annotated[
        bool, typer.Option("--respect-robots/--ignore-robots")
    ] = True,
) -> None:
    """Resume a previously-interrupted scrape job."""
    asyncio.run(
        _run_resume(
            job_id=job_id,
            out=out,
            retry_failed=retry_failed,
            timeout=timeout,
            tier=tier,
            proxy=proxy,
            rate_limit=rate_limit,
            respect_robots=respect_robots,
        )
    )


async def _run_resume(
    *,
    job_id: str,
    out: Path,
    retry_failed: bool,
    timeout: float,  # noqa: ASYNC109
    tier: str,
    proxy: str | None,
    rate_limit: float,
    respect_robots: bool,
) -> None:
    from gimmethatdata.core.pipeline import ScrapeOptions
    from gimmethatdata.core.runner import JobEvent, run_resume_job

    options = ScrapeOptions(respect_robots=respect_robots)

    def on_event(event: JobEvent) -> None:
        if event.kind == "page_done":
            console.print(
                f"[green]done[/] {event.url} -> [dim]{event.output_dir}[/] (tier={event.tier})"
            )
        elif event.kind == "page_failed":
            console.print(f"[red]fail[/] {event.url}: {event.error}")
        elif event.kind == "finished":
            summary = ", ".join(f"{k}={v}" for k, v in (event.summary or {}).items())
            console.print(f"[bold]job {event.job_id} finished[/] · {summary}")

    await run_resume_job(
        job_id=job_id,
        out=out,
        retry_failed=retry_failed,
        options=options,
        timeout=timeout,
        tier=tier,
        proxy=proxy,
        rate_limit=rate_limit,
        on_event=on_event,
    )


@app.command()
def sitemap(
    domain_dir: Annotated[
        Path,
        typer.Argument(
            help="Path to a `<out_root>/<domain>` directory that holds `_site.sqlite`.",
        ),
    ],
    seed: Annotated[
        str | None,
        typer.Option(
            "--seed",
            help="Seed URL used to root the tree (default: shallowest discovered node).",
        ),
    ] = None,
) -> None:
    """(Re)build `_sitemap.json` + `_sitemap.md` from a crawl's `_site.sqlite`."""
    asyncio.run(_run_sitemap(domain_dir=domain_dir, seed=seed))


async def _run_sitemap(*, domain_dir: Path, seed: str | None) -> None:
    from gimmethatdata.crawl.sitemap_writer import write_sitemap_from_frontier

    site_db = domain_dir / "_site.sqlite"
    if not site_db.exists():
        raise typer.BadParameter(f"no `_site.sqlite` at {site_db}")
    json_path, md_path = await write_sitemap_from_frontier(domain_dir, seed=seed)
    console.print(f"[green]wrote[/] {json_path}")
    console.print(f"[green]wrote[/] {md_path}")


@app.command(name="export-pdf")
def export_pdf(
    path: Annotated[
        Path,
        typer.Argument(
            help=(
                "Path to scrape output. Can be a single page dir (containing "
                "content.md), a domain dir (`<out>/<domain>/`), or any folder; "
                "every content.md beneath it is included."
            )
        ),
    ],
    out: Annotated[
        Path | None,
        typer.Option(
            "--out", "-o",
            help="PDF output path (default: `<path>/export.pdf`).",
        ),
    ] = None,
    title: Annotated[
        str | None,
        typer.Option("--title", help="Document title (default: derived from path)."),
    ] = None,
    page_size: Annotated[
        str,
        typer.Option(
            "--page-size",
            help="Page size: A4, Letter, Legal, A3, A5.",
        ),
    ] = "A4",
    keep_html: Annotated[
        bool,
        typer.Option(
            "--keep-html",
            help="Keep the intermediate `_export.html` next to the assets.",
        ),
    ] = False,
) -> None:
    """Export scraped pages to a single PDF with embedded images + media link badges.

    Examples:

      gimmethatdata export-pdf .ignore/out/example.com/_index
      gimmethatdata export-pdf .ignore/out/example.com -o report.pdf
      gimmethatdata export-pdf .ignore/udaysinh-full/udaysinh.me --title "udaysinh.me"
    """
    resolved_out = out or (path / "export.pdf")
    asyncio.run(_run_export_pdf(path, resolved_out, title, page_size, keep_html))


async def _run_export_pdf(
    source: Path,
    out: Path,
    title: str | None,
    page_size: str,
    keep_html: bool,
) -> None:
    from gimmethatdata.export.pdf import export_to_pdf

    if not source.exists():
        raise typer.BadParameter(f"path does not exist: {source}")
    console.print(f"[cyan]exporting[/] {source} -> [bold]{out}[/]")
    try:
        result = await export_to_pdf(
            source, out=out, title=title, page_size=page_size, keep_html=keep_html,
        )
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1) from exc
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1) from exc
    size_kb = result.stat().st_size // 1024
    console.print(f"[green]done[/] · {result} ({size_kb} KB)")


@app.command()
def setup(
    full: Annotated[
        bool, typer.Option("--full", help="Also install the `ocr` extra (Tesseract still needed at OS level).")
    ] = False,
    no_browsers: Annotated[
        bool, typer.Option("--no-browsers", help="Skip downloading Playwright's chromium binary.")
    ] = False,
    skip_sync: Annotated[
        bool, typer.Option("--skip-sync", help="Skip the `uv sync` step (only browser install + doctor).")
    ] = False,
) -> None:
    """One-shot install: extras + browsers + sanity check.

    Replaces the manual chain:
      uv sync --extra bypass --extra media --extra state [--extra ocr]
      uv run playwright install chromium
    """
    import shutil
    import subprocess
    import sys

    uv = shutil.which("uv")
    if uv is None:
        console.print(
            "[red]uv not found on PATH[/]. "
            "Install it from https://docs.astral.sh/uv/ then retry."
        )
        raise typer.Exit(code=1)

    extras = ["bypass", "media", "state", "pdf"]
    if full:
        extras.append("ocr")

    if not skip_sync:
        console.rule(f"[bold cyan]1/4 · uv sync --extra {' --extra '.join(extras)}[/]")
        sync_cmd = [uv, "sync"]
        for extra in extras:
            sync_cmd += ["--extra", extra]
        result = subprocess.run(sync_cmd, check=False)
        if result.returncode != 0:
            console.print("[red]uv sync failed[/]")
            raise typer.Exit(code=result.returncode)
    else:
        console.rule("[bold cyan]1/4 · skipped uv sync[/]")

    if not no_browsers:
        install_cmd = [uv, "run", "playwright", "install", "chromium"]
        if sys.platform == "linux":
            install_cmd.append("--with-deps")
        console.rule(f"[bold cyan]2/4 · {' '.join(install_cmd[2:])}[/]")
        result = subprocess.run(install_cmd, check=False)
        if result.returncode != 0:
            console.print("[red]playwright install failed[/]")
            raise typer.Exit(code=result.returncode)

        console.rule("[bold cyan]3/4 · verifying chromium launches[/]")
        ok, message = _verify_chromium_launch()
        if not ok:
            console.print(f"[red]chromium verification failed[/] · {message}")
            console.print(
                "[yellow]hint:[/] re-run [cyan]uv run gimmethatdata setup[/] "
                "or [cyan]uv run playwright install chromium[/] manually."
            )
            raise typer.Exit(code=1)
        console.print(f"  [green]ok[/] · chromium reports version [bold]{message}[/]")
    else:
        console.rule("[bold cyan]2/4 · skipped playwright install[/]")
        console.rule("[bold cyan]3/4 · skipped chromium verify[/]")

    console.rule("[bold cyan]4/4 · doctor[/]")
    _doctor_report(check_tesseract=full)

    console.print(
        "\n[bold green]Setup complete.[/] try: "
        "[cyan]uv run gimmethatdata scrape https://example.com --out .ignore/out[/]"
        " or [cyan]uv run gimmethatdata tui[/]."
    )


def _verify_chromium_launch() -> tuple[bool, str]:
    """Actually launch a headless chromium briefly. Returns (ok, message_or_version)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False, "playwright python package not installed (run `uv sync --extra bypass`)"
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                version = browser.version
            finally:
                browser.close()
        return True, version
    except Exception as exc:
        return False, str(exc).splitlines()[0][:200]


def _chromium_expected_path() -> tuple[Path | None, bool]:
    """Return Playwright's expected chromium path and whether it exists."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None, False
    try:
        with sync_playwright() as pw:
            path_str = pw.chromium.executable_path
    except Exception:
        return None, False
    if not path_str:
        return None, False
    path = Path(path_str)
    return path, path.exists()


def _doctor_report(*, check_tesseract: bool) -> None:
    """Inspect optional system binaries the runtime can use."""
    import shutil

    def check(binary: str, why: str, *, required: bool = False) -> None:
        path = shutil.which(binary)
        if path:
            console.print(f"  [green]found[/]    {binary:<12} [dim]{path}[/]")
        else:
            tag = "[red]missing[/]" if required else "[yellow]missing[/]"
            console.print(f"  {tag}  {binary:<12} [dim]{why}[/]")

    check("uv", "package manager (required to run this CLI)", required=True)
    check("ffmpeg", "yt-dlp needs ffmpeg for video muxing")
    if check_tesseract:
        check("tesseract", "needed by the --ocr flag")

    try:
        from playwright.async_api import async_playwright  # noqa: F401

        console.print("  [green]found[/]    playwright   [dim](python package)[/]")
        chromium_path, exists = _chromium_expected_path()
        if chromium_path is None:
            console.print(
                "  [yellow]missing[/]  chromium     "
                "[dim]playwright can't resolve a path — run `gimmethatdata setup`[/]"
            )
        elif exists:
            console.print(f"  [green]found[/]    chromium     [dim]{chromium_path}[/]")
        else:
            console.print(
                f"  [red]missing[/]  chromium     "
                f"[dim]expected {chromium_path} — run `gimmethatdata setup`[/]"
            )
    except ImportError:
        console.print(
            "  [yellow]missing[/]  playwright   [dim]install with `uv sync --extra bypass`[/]"
        )


@app.command()
def doctor() -> None:
    """Diagnose missing optional dependencies without installing anything."""
    console.rule("[bold cyan]gimmethatdata · doctor[/]")
    _doctor_report(check_tesseract=True)


@app.command()
def config() -> None:
    """Show resolved configuration."""
    from gimmethatdata.config import load_settings

    settings = load_settings()
    console.print(settings.model_dump())


if __name__ == "__main__":
    app()
