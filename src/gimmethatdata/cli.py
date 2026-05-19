"""Typer CLI entry point for gimmethatdata."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
from rich.console import Console

from gimmethatdata import __version__
from gimmethatdata.core.models import AssetKind
from gimmethatdata.logging_setup import configure_logging

if TYPE_CHECKING:
    from gimmethatdata.instagram import InstagramClient

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
    auth: Annotated[
        str | None,
        typer.Option(
            "--auth",
            help="Auth credentials. Format: basic:user:pass  or  bearer:<token>.",
        ),
    ] = None,
    cookie: Annotated[
        list[str] | None,
        typer.Option(
            "--cookie",
            help="Cookie pair (k=v). Repeatable; can also be a full 'k=v; k2=v2' string.",
        ),
    ] = None,
    cookies_file: Annotated[
        Path | None,
        typer.Option(
            "--cookies-file",
            help="Path to a Netscape-format cookies.txt file.",
        ),
    ] = None,
    header: Annotated[
        list[str] | None,
        typer.Option(
            "--header", "-H",
            help="Extra request header 'Name: Value'. Repeatable.",
        ),
    ] = None,
    cache_dir: Annotated[
        Path | None,
        typer.Option(
            "--cache-dir",
            help="Enable on-disk HTTP cache (ETag/Last-Modified) at the given dir.",
        ),
    ] = None,
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
            auth_arg=auth,
            cookies_arg=cookie,
            cookies_file=cookies_file,
            headers_arg=header,
            cache_dir=cache_dir,
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
    auth_arg: str | None,
    cookies_arg: list[str] | None,
    cookies_file: Path | None,
    headers_arg: list[str] | None,
    cache_dir: Path | None,
    preset_name: str,
    ocr: bool,
) -> None:
    from gimmethatdata.core.pipeline import ScrapeOptions
    from gimmethatdata.core.runner import ScrapeJobSpec
    from gimmethatdata.fetch.auth import AuthConfig
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
    try:
        auth_cfg = AuthConfig.from_cli(
            auth=auth_arg,
            cookies_arg=cookies_arg,
            cookies_file=cookies_file,
            headers_arg=headers_arg,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    spec = ScrapeJobSpec(
        urls=urls,
        out=out,
        options=options,
        job_id=job_id,
        timeout=timeout,
        tier=tier,
        proxy=proxy,
        rate_limit=rate_limit,
        auth=auth_cfg,
        cache_dir=cache_dir,
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
    include_subdomains: Annotated[
        bool,
        typer.Option(
            "--include-subdomains",
            help="Seed frontier from crt.sh-discovered subdomains too.",
        ),
    ] = False,
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
            include_subdomains=include_subdomains,
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
    include_subdomains: bool,
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
        include_subdomains=include_subdomains,
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


@app.command()
def search(
    query: Annotated[str, typer.Argument(help="FTS query — supports phrases + multi-word.")],
    out: Annotated[
        Path,
        typer.Option("--out", "-o", help="Out-root that holds scraped pages + index."),
    ] = Path("out"),
    reindex: Annotated[
        bool,
        typer.Option("--reindex", help="Rebuild the FTS index before searching."),
    ] = False,
    limit: Annotated[
        int, typer.Option("--limit", help="Max hits to print.")
    ] = 25,
) -> None:
    """Full-text search across every scraped `content.md` under `--out`."""
    from gimmethatdata.persist.search import SearchIndex, index_all

    if reindex or not (out / "_search.sqlite").exists():
        if not out.exists():
            raise typer.BadParameter(f"out-root does not exist: {out}")
        count = index_all(out)
        console.print(f"[cyan]indexed[/] {count} pages -> {out / '_search.sqlite'}")
    with SearchIndex(out / "_search.sqlite") as idx:
        hits = idx.search(query, limit=limit)
    if not hits:
        console.print("[yellow]no matches[/]")
        return
    for hit in hits:
        console.print(f"[bold]{hit.title}[/] · [dim]{hit.url}[/]")
        if hit.snippet:
            console.print(f"  {hit.snippet}", style="dim")
        console.print()
    console.print(f"[bold]{len(hits)} hits[/]")


@app.command()
def diff(
    before: Annotated[Path, typer.Argument(help="Older snapshot directory.")],
    after: Annotated[Path, typer.Argument(help="Newer snapshot directory.")],
    out: Annotated[
        Path | None,
        typer.Option(
            "--out", "-o",
            help="Write the diff to this Markdown file (default: stdout).",
        ),
    ] = None,
) -> None:
    """Compare two scrape snapshots; surface added / removed / changed pages."""
    from gimmethatdata.export.diff import compute_diff, render_diff_markdown

    if not before.exists():
        raise typer.BadParameter(f"before path does not exist: {before}")
    if not after.exists():
        raise typer.BadParameter(f"after path does not exist: {after}")
    diff_result = compute_diff(before, after)
    summary = diff_result.summary()
    console.print(
        f"[bold]diff[/] · added={summary['added']} removed={summary['removed']} "
        f"changed={summary['changed']} unchanged={summary['unchanged']}"
    )
    md = render_diff_markdown(diff_result)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md, encoding="utf-8")
        console.print(f"[green]wrote[/] {out}")
    else:
        console.print(md)


@app.command()
def watch(
    target: Annotated[
        str,
        typer.Argument(help="URL to scrape (single page) or seed URL to crawl each tick."),
    ],
    every: Annotated[
        str, typer.Option("--every", help="Interval: 30s, 5m, 1h, 12d.")
    ] = "1h",
    mode: Annotated[
        str,
        typer.Option(
            "--mode",
            help="Per-tick action: `scrape` (single page) or `crawl` (full site).",
        ),
    ] = "scrape",
    iterations: Annotated[
        int | None,
        typer.Option(
            "--iterations", "-n",
            help="Stop after this many ticks (default: run forever).",
        ),
    ] = None,
    out: Annotated[
        Path,
        typer.Option("--out", "-o", help="Root dir for snapshots."),
    ] = Path("watch"),
    depth: Annotated[
        int, typer.Option("--depth", help="Crawl depth (mode=crawl only).")
    ] = 1,
    max_pages: Annotated[
        int, typer.Option("--max-pages", help="Crawl page cap (mode=crawl only).")
    ] = 50,
) -> None:
    """Re-scrape periodically and diff each run against the previous one."""
    from gimmethatdata.core.watch import parse_interval

    try:
        interval = parse_interval(every)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if mode not in {"scrape", "crawl"}:
        raise typer.BadParameter("--mode must be 'scrape' or 'crawl'")
    asyncio.run(
        _run_watch(
            target=target,
            interval_seconds=interval,
            mode=mode,
            iterations=iterations,
            out=out,
            depth=depth,
            max_pages=max_pages,
        )
    )


async def _run_watch(
    *,
    target: str,
    interval_seconds: float,
    mode: str,
    iterations: int | None,
    out: Path,
    depth: int,
    max_pages: int,
) -> None:
    from gimmethatdata.core.pipeline import ScrapeOptions
    from gimmethatdata.core.runner import (
        CrawlJobSpec,
        ScrapeJobSpec,
        run_crawl_job,
        run_scrape_job,
    )
    from gimmethatdata.core.watch import WatchTick, watch_loop
    from gimmethatdata.crawl.frontier import ScopeMode

    async def runner(snapshot_dir: Path) -> None:
        if mode == "scrape":
            scrape_spec = ScrapeJobSpec(
                urls=[target],
                out=snapshot_dir,
                options=ScrapeOptions(),
            )
            await run_scrape_job(scrape_spec)
        else:
            crawl_spec = CrawlJobSpec(
                seed_url=target,
                out=snapshot_dir,
                depth=depth,
                max_pages=max_pages,
                scope=ScopeMode.SAME_DOMAIN,
                options=ScrapeOptions(),
            )
            await run_crawl_job(crawl_spec)

    async def on_tick(tick: WatchTick) -> None:
        if tick.diff is None:
            console.print(f"[cyan]tick {tick.index}[/] baseline snapshot @ {tick.snapshot_dir}")
            return
        summary = tick.diff.summary()
        console.print(
            f"[cyan]tick {tick.index}[/] · added={summary['added']} "
            f"removed={summary['removed']} changed={summary['changed']} "
            f"unchanged={summary['unchanged']} @ {tick.snapshot_dir}"
        )

    await watch_loop(
        interval_seconds=interval_seconds,
        runner=runner,
        snapshots_root=out,
        iterations=iterations,
        on_tick=on_tick,
    )


@app.command(name="ig-hashtag")
def ig_hashtag(
    tag: Annotated[str, typer.Argument(help="Hashtag without the leading #.")],
    out: Annotated[Path, typer.Option("--out", "-o")] = Path("out"),
    sort: Annotated[str, typer.Option("--sort", help="top | recent")] = "top",
    amount: Annotated[int, typer.Option("--amount", help="Max posts.")] = 50,
    session_file: Annotated[
        Path | None,
        typer.Option("--session-file", help="Session file (login almost always needed)."),
    ] = None,
    login_user: Annotated[str | None, typer.Option("--login")] = None,
    password: Annotated[str | None, typer.Option("--password")] = None,
) -> None:
    """Archive top/recent posts for a hashtag."""
    from gimmethatdata.instagram.discovery import discover_hashtag

    if sort not in {"top", "recent"}:
        raise typer.BadParameter("--sort must be 'top' or 'recent'")
    client = _ig_client_from_flags(
        login_user=login_user, password=password, session_file=session_file
    )
    report = discover_hashtag(
        client, tag, out_root=out, sort=sort, amount=amount,
        on_progress=lambda e, p: console.print(f"  [green]saved[/] [dim]{p.get('shortcode')}[/]")
        if e == "discovery_saved" else None,
    )
    console.print(
        f"[bold]hashtag #{tag}[/] saved={report.saved} skipped={report.skipped_existing} "
        f"images={report.images_downloaded} -> {report.target_dir}"
    )
    for err in report.errors[:5]:
        console.print(f"  [yellow]·[/] {err}")


@app.command(name="ig-location")
def ig_location(
    location_pk: Annotated[int, typer.Argument(help="Numeric Instagram location id.")],
    out: Annotated[Path, typer.Option("--out", "-o")] = Path("out"),
    sort: Annotated[str, typer.Option("--sort", help="top | recent")] = "top",
    amount: Annotated[int, typer.Option("--amount")] = 50,
    session_file: Annotated[Path | None, typer.Option("--session-file")] = None,
    login_user: Annotated[str | None, typer.Option("--login")] = None,
    password: Annotated[str | None, typer.Option("--password")] = None,
) -> None:
    """Archive posts for an Instagram location PK."""
    from gimmethatdata.instagram.discovery import discover_location

    if sort not in {"top", "recent"}:
        raise typer.BadParameter("--sort must be 'top' or 'recent'")
    client = _ig_client_from_flags(
        login_user=login_user, password=password, session_file=session_file
    )
    report = discover_location(
        client, location_pk, out_root=out, sort=sort, amount=amount,
        on_progress=lambda e, p: console.print(f"  [green]saved[/] [dim]{p.get('shortcode')}[/]")
        if e == "discovery_saved" else None,
    )
    console.print(
        f"[bold]location {location_pk}[/] saved={report.saved} "
        f"skipped={report.skipped_existing} -> {report.target_dir}"
    )


@app.command(name="ig-music")
def ig_music(
    track_id: Annotated[int, typer.Argument(help="Numeric IG audio/track id.")],
    out: Annotated[Path, typer.Option("--out", "-o")] = Path("out"),
    amount: Annotated[int, typer.Option("--amount")] = 50,
    session_file: Annotated[Path | None, typer.Option("--session-file")] = None,
    login_user: Annotated[str | None, typer.Option("--login")] = None,
    password: Annotated[str | None, typer.Option("--password")] = None,
) -> None:
    """Archive posts that use a given music/audio track."""
    from gimmethatdata.instagram.discovery import discover_music

    client = _ig_client_from_flags(
        login_user=login_user, password=password, session_file=session_file
    )
    report = discover_music(
        client, track_id, out_root=out, amount=amount,
        on_progress=lambda e, p: console.print(f"  [green]saved[/] [dim]{p.get('shortcode')}[/]")
        if e == "discovery_saved" else None,
    )
    console.print(
        f"[bold]music {track_id}[/] saved={report.saved} "
        f"skipped={report.skipped_existing} -> {report.target_dir}"
    )
    for err in report.errors[:5]:
        console.print(f"  [yellow]·[/] {err}")


@app.command(name="ig-compare")
def ig_compare(
    left: Annotated[Path, typer.Argument(help="First profile dir (e.g. out/instagram/a).")],
    right: Annotated[Path, typer.Argument(help="Second profile dir.")],
    out: Annotated[
        Path | None,
        typer.Option("--out", help="Write report into this dir (default: alongside profiles)."),
    ] = None,
) -> None:
    """Compare two scraped IG profiles — metric deltas + commenter overlap."""
    from gimmethatdata.instagram import compare_profiles, write_compare_report

    report = compare_profiles(left, right)
    md_path, json_path = write_compare_report(report, out_dir=out)
    console.print(f"[green]wrote[/] {md_path}")
    console.print(f"[green]wrote[/] {json_path}")
    console.print(
        f"Audience overlap: {len(report.shared_commenters)} shared "
        f"(jaccard {report.jaccard_commenters:.3f})"
    )


@app.command(name="ig-engagement")
def ig_engagement(
    profile_dir: Annotated[Path, typer.Argument(help="Path to out/instagram/<user>.")],
) -> None:
    """(Re)build the engagement insights report for a downloaded profile."""
    from gimmethatdata.instagram import analyze_engagement, write_engagement_report

    if not profile_dir.exists():
        raise typer.BadParameter(f"path does not exist: {profile_dir}")
    report = analyze_engagement(profile_dir)
    md_path, json_path = write_engagement_report(report)
    console.print(f"[green]wrote[/] {md_path}")
    console.print(f"[green]wrote[/] {json_path}")


@app.command(name="ig-contact-sheet")
def ig_contact_sheet(
    profile_dir: Annotated[Path, typer.Argument(help="Path to out/instagram/<user>.")],
    out: Annotated[
        Path | None,
        typer.Option("--out", help="Output HTML path (default: <profile>/_contact_sheet.html)."),
    ] = None,
) -> None:
    """Render every downloaded image into one browsable HTML grid."""
    from gimmethatdata.instagram import write_contact_sheet

    if not profile_dir.exists():
        raise typer.BadParameter(f"path does not exist: {profile_dir}")
    path = write_contact_sheet(profile_dir, out=out)
    console.print(f"[green]wrote[/] {path}")


def _ig_client_from_flags(
    *, login_user: str | None, password: str | None, session_file: Path | None
) -> InstagramClient:
    from gimmethatdata.instagram import IGLoginError, InstagramClient

    try:
        if session_file is not None and session_file.exists():
            return InstagramClient.from_session_file(
                username=login_user or "anonymous",
                session_file=session_file,
            )
        if login_user is not None:
            pw = password if password is not None else typer.prompt(
                "password", hide_input=True
            )
            return InstagramClient.login(
                username=login_user, password=pw, session_file=session_file,
            )
        return InstagramClient.anonymous()
    except IGLoginError as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command(name="ig-import-cookie")
def ig_import_cookie(
    username: Annotated[
        str,
        typer.Argument(help="The IG account the cookie belongs to (your own handle)."),
    ],
    sessionid: Annotated[
        str,
        typer.Option(
            "--sessionid",
            help="Value of the `sessionid` cookie copied from your browser.",
        ),
    ],
    csrftoken: Annotated[
        str | None,
        typer.Option("--csrftoken", help="Optional `csrftoken` cookie value."),
    ] = None,
    session_file: Annotated[
        Path,
        typer.Option(
            "--session-file",
            help="Where to write the resulting instaloader session file.",
        ),
    ] = Path(".ignore/ig-session"),
) -> None:
    """Mint an instaloader session file from a browser `sessionid` cookie.

    Use this when `--login` keeps returning IG's 'Unexpected null login result' —
    a real browser still works, so we ride on its cookie. Open instagram.com,
    log in normally, then copy the `sessionid` cookie from DevTools.
    """
    from gimmethatdata.instagram.client import IGLoginError, import_session_from_cookie

    try:
        path = import_session_from_cookie(
            username=username,
            sessionid=sessionid,
            session_file=session_file,
        )
    except IGLoginError as exc:
        raise typer.BadParameter(str(exc)) from exc
    console.print(f"[green]wrote[/] {path}")
    console.print(
        f"Now run: [cyan]uv run gimmethatdata instagram <user> --session-file {path}[/]"
    )


@app.command()
def instagram(
    username: Annotated[
        str,
        typer.Argument(
            help="Instagram handle (no @). Or comma-separated list: a,b,c.",
        ),
    ],
    users_file: Annotated[
        Path | None,
        typer.Option(
            "--users-file",
            help="Read handles from a file (one per line, # comments allowed).",
        ),
    ] = None,
    out: Annotated[
        Path,
        typer.Option("--out", "-o", help="Output root."),
    ] = Path("out"),
    login_user: Annotated[
        str | None,
        typer.Option("--login", help="Login as this username (prompted for password if --password isn't set)."),
    ] = None,
    password: Annotated[
        str | None,
        typer.Option(
            "--password",
            help="Password for --login. Prefer --session-file in scripts.",
        ),
    ] = None,
    session_file: Annotated[
        Path | None,
        typer.Option(
            "--session-file",
            help="Reuse / save an instagrapi session file (preferred for repeat runs).",
        ),
    ] = None,
    verification_code: Annotated[
        str | None,
        typer.Option(
            "--verification-code",
            help="6-digit 2FA code (if the account has 2FA enabled).",
        ),
    ] = None,
    posts: Annotated[bool, typer.Option("--posts/--no-posts")] = True,
    reels: Annotated[bool, typer.Option("--reels/--no-reels")] = True,
    highlights: Annotated[bool, typer.Option("--highlights")] = False,
    stories: Annotated[bool, typer.Option("--stories")] = False,
    comments: Annotated[
        bool,
        typer.Option(
            "--comments/--no-comments",
            help="Collect comments (needs login). Auto-skipped when anonymous.",
        ),
    ] = True,
    analyze: Annotated[
        bool,
        typer.Option(
            "--analyze-comments/--no-analyze-comments",
            help="After download, run the comment-insights report.",
        ),
    ] = True,
    download_images: Annotated[
        bool, typer.Option("--download-images/--no-download-images")
    ] = True,
    limit: Annotated[
        int | None, typer.Option("--limit", help="Cap the number of posts/reels fetched.")
    ] = None,
    pdf: Annotated[
        bool,
        typer.Option("--pdf", help="Auto-export the downloaded profile to PDF after."),
    ] = False,
    tagged: Annotated[
        bool,
        typer.Option("--tagged", help="Also archive posts where the user was tagged by others."),
    ] = False,
    likers: Annotated[
        bool,
        typer.Option("--likers", help="Save the list of users who liked each post (login required)."),
    ] = False,
    replies: Annotated[
        bool,
        typer.Option(
            "--comment-replies",
            help="Fetch nested comment replies (slower; one API call per comment with children).",
        ),
    ] = False,
    enrich_locations: Annotated[
        bool,
        typer.Option(
            "--enrich-locations",
            help="Resolve location names to lat/lng/address (one extra API call per unique loc).",
        ),
    ] = False,
    ocr_images: Annotated[
        bool,
        typer.Option("--ocr-images", help="Run OCR over downloaded photos and append to content.md."),
    ] = False,
    since: Annotated[
        str | None,
        typer.Option(
            "--since",
            help="Only fetch posts on/after this date (YYYY-MM-DD). Incremental archive.",
        ),
    ] = None,
    no_resume: Annotated[
        bool,
        typer.Option("--no-resume", help="Re-download even if a shortcode is already on disk."),
    ] = False,
    analytics: Annotated[
        bool,
        typer.Option(
            "--analytics/--no-analytics",
            help="After download, build the engagement insights report.",
        ),
    ] = True,
    contact_sheet: Annotated[
        bool,
        typer.Option("--contact-sheet", help="Generate `_contact_sheet.html` after download."),
    ] = False,
) -> None:
    """Archive an Instagram profile (posts / reels / highlights / comments).

    No video downloads — only photos + cover frames + caption + metadata.

    Note: Instagram's ToS prohibits unauthorized automated access. Only use this
    on accounts you own, accounts that grant you permission, or genuinely public
    profiles where archiving falls under your jurisdiction's fair-use rules.
    """
    if password is not None and login_user is None:
        raise typer.BadParameter("--password requires --login")
    if (highlights or stories or comments or likers or tagged) and not (login_user or session_file):
        console.print(
            "[yellow]note:[/] highlights / stories / comments / likers / tagged "
            "need login. Pass --login <user> or --session-file <path>."
        )
    handles = _collect_ig_handles(username, users_file)
    since_dt: datetime | None = None
    if since is not None:
        try:
            since_dt = datetime.fromisoformat(since).replace(tzinfo=UTC)
        except ValueError as exc:
            raise typer.BadParameter(f"--since must be YYYY-MM-DD: {exc}") from exc
    asyncio.run(
        _run_instagram(
            handles=handles,
            out=out,
            login_user=login_user,
            password=password,
            session_file=session_file,
            verification_code=verification_code,
            posts=posts,
            reels=reels,
            highlights=highlights,
            stories=stories,
            tagged=tagged,
            comments=comments,
            likers=likers,
            replies=replies,
            enrich_locations=enrich_locations,
            ocr_images=ocr_images,
            since_dt=since_dt,
            resume=not no_resume,
            analyze=analyze,
            analytics=analytics,
            download_images=download_images,
            limit=limit,
            pdf=pdf,
            contact_sheet=contact_sheet,
        )
    )


def _collect_ig_handles(username: str, users_file: Path | None) -> list[str]:
    handles: list[str] = []
    for raw in username.split(","):
        handle = raw.strip().lstrip("@")
        if handle:
            handles.append(handle)
    if users_file is not None:
        for line in users_file.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            handles.append(stripped.lstrip("@"))
    seen: set[str] = set()
    unique: list[str] = []
    for h in handles:
        if h not in seen:
            seen.add(h)
            unique.append(h)
    if not unique:
        raise typer.BadParameter("no Instagram handles supplied")
    return unique


async def _run_instagram(
    *,
    handles: list[str],
    out: Path,
    login_user: str | None,
    password: str | None,
    session_file: Path | None,
    verification_code: str | None,
    posts: bool,
    reels: bool,
    highlights: bool,
    stories: bool,
    tagged: bool,
    comments: bool,
    likers: bool,
    replies: bool,
    enrich_locations: bool,
    ocr_images: bool,
    since_dt: datetime | None,
    resume: bool,
    analyze: bool,
    analytics: bool,
    download_images: bool,
    limit: int | None,
    pdf: bool,
    contact_sheet: bool,
) -> None:
    from gimmethatdata.instagram import (
        IGDownloadOptions,
        IGLoginError,
        InstagramClient,
        analyze_engagement,
        download_profile,
        write_contact_sheet,
        write_engagement_report,
    )
    from gimmethatdata.instagram.comments import analyze as analyze_comments
    from gimmethatdata.instagram.comments import write_report

    try:
        if session_file is not None and session_file.exists():
            client = InstagramClient.from_session_file(
                username=login_user or handles[0],
                session_file=session_file,
            )
        elif login_user is not None:
            pw = password if password is not None else typer.prompt("password", hide_input=True)
            client = InstagramClient.login(
                username=login_user,
                password=pw,
                session_file=session_file,
                verification_code=verification_code,
            )
        else:
            client = InstagramClient.anonymous()
    except IGLoginError as exc:
        raise typer.BadParameter(str(exc)) from exc

    base_options = IGDownloadOptions(
        fetch_posts=posts,
        fetch_reels=reels,
        fetch_highlights=highlights,
        fetch_stories=stories,
        fetch_tagged=tagged,
        fetch_comments=comments and client.logged_in_as is not None,
        fetch_likers=likers and client.logged_in_as is not None,
        fetch_comment_replies=replies,
        enrich_locations=enrich_locations,
        ocr_images=ocr_images,
        download_images=download_images,
        limit=limit,
        since=since_dt,
        resume=resume,
    )

    def progress(event: str, payload: dict[str, object]) -> None:
        if event == "profile_loaded":
            console.print(
                f"[cyan]profile[/] @{payload.get('username')}  "
                f"(private={payload.get('is_private')})"
            )
        elif event == "post_saved":
            console.print(
                f"  [green]saved[/] {payload.get('kind')} "
                f"[dim]{payload.get('shortcode')}[/]"
            )
        elif event == "post_skipped":
            console.print(
                f"  [dim]skip[/] {payload.get('shortcode')} ({payload.get('reason')})"
            )
        elif event == "tagged_saved":
            console.print(f"  [green]tagged[/] [dim]{payload.get('shortcode')}[/]")
        elif event == "highlight_saved":
            console.print(
                f"  [green]highlight[/] {payload.get('title')} ({payload.get('items')} items)"
            )
        elif event == "story_saved":
            console.print(f"  [green]story[/] {payload.get('mediaid')}")

    for handle in handles:
        console.print(
            f"[bold]downloading[/] instagram/@{handle} -> {out / 'instagram' / handle}"
        )
        try:
            report = await asyncio.to_thread(
                download_profile,
                client,
                handle,
                out_root=out,
                options=base_options,
                on_progress=progress,
            )
        except RuntimeError as exc:
            console.print(f"[red]{handle}:[/] {exc}")
            continue

        profile_root = out / "instagram" / handle
        console.print(
            f"[bold]done @{handle}[/] · posts={report.posts} reels={report.reels} "
            f"tagged={report.tagged} highlights={report.highlights} "
            f"stories={report.stories} images={report.images_downloaded} "
            f"comments={report.comments_collected} likers={report.likers_collected} "
            f"skipped={report.skipped_existing}"
        )
        if report.errors:
            console.print(f"[yellow]warnings:[/] {len(report.errors)}")
            for err in report.errors[:5]:
                console.print(f"  · {err}")

        if analyze:
            insights = analyze_comments(profile_root)
            md_path, _json_path = write_report(insights)
            console.print(f"[green]comment report[/] -> {md_path}")
            if insights.top_commenters:
                tops = ", ".join(f"@{u} ({n})" for u, n in insights.top_commenters[:5])
                console.print(
                    f"  unique commenters: {insights.unique_commenters} · top: {tops}"
                )

        if analytics:
            engagement = analyze_engagement(profile_root)
            md_path, _json_path = write_engagement_report(engagement)
            console.print(f"[green]engagement report[/] -> {md_path}")
            best = engagement.best_by(metric="engagement", top=3)
            if best:
                console.print(
                    "  top engagement: "
                    + " · ".join(
                        f"{p.shortcode}({p.likes}❤ {p.comments}💬)" for p in best
                    )
                )

        if contact_sheet:
            sheet_path = write_contact_sheet(profile_root)
            console.print(f"[green]contact sheet[/] -> {sheet_path}")

        if pdf:
            from gimmethatdata.export.pdf import export_to_pdf

            pdf_path = profile_root / f"{handle}.pdf"
            console.print(f"[cyan]exporting PDF[/] -> {pdf_path}")
            await export_to_pdf(profile_root, out=pdf_path, title=f"@{handle} archive")
            console.print(
                f"[green]PDF[/] {pdf_path} ({pdf_path.stat().st_size // 1024} KB)"
            )


@app.command()
def subdomains(
    seed: Annotated[
        str, typer.Argument(help="Base URL or domain — e.g. https://example.com or example.com")
    ],
    max_results: Annotated[
        int, typer.Option("--max", help="Cap on returned subdomains.")
    ] = 200,
) -> None:
    """Discover subdomains via Certificate Transparency (crt.sh)."""
    asyncio.run(_run_subdomains(seed, max_results))


async def _run_subdomains(seed: str, max_results: int) -> None:
    from gimmethatdata.config import load_settings
    from gimmethatdata.crawl.subdomain import discover_subdomains

    settings = load_settings()
    if "://" not in seed:
        seed = f"https://{seed}/"
    hosts = await discover_subdomains(
        seed, user_agent=settings.fetch.user_agent, max_subdomains=max_results
    )
    if not hosts:
        console.print("[yellow]no subdomains found[/]")
        return
    for host in hosts:
        console.print(host)
    console.print(f"\n[bold]{len(hosts)} subdomains[/]")


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
        extras.extend(["ocr", "instagram"])

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
