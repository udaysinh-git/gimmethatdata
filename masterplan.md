# gimmethatdata — roadmap

This file is my working notes on what gimmethatdata is, why it's built this way, and where it's going next. Not a spec, not a marketing page — just enough so I (or anyone else reading the repo) can pick it up cold.

## what it is

A Python CLI + Textual TUI that scrapes any site — one page, a list of pages, or the whole thing — and dumps it into a clean folder of Markdown + asset manifests. Tiered anti-bot bypass, proxy-aware, resumable, optional PDF export.

Three scrape modes:

- per-page → `gimmethatdata scrape <url>`
- selected URLs → `gimmethatdata scrape <url1> <url2> ...` or `--urls-file`
- entire site → `gimmethatdata crawl <url>` (with depth + page-count caps)

## design choices

| Concern | Choice | Why |
| --- | --- | --- |
| Package manager | [`uv`](https://docs.astral.sh/uv/) | fast, lockfile-driven, single binary |
| CLI | [Typer](https://typer.tiangolo.com/) | nice subcommand help out of the box |
| TUI | [Textual](https://textual.textualize.io/) | real interactive screens, async-native |
| Tier 1 fetch | `httpx[http2]` | the 99% case, cheap |
| Tier 2 fetch | `curl_cffi` | browser TLS fingerprint; beats basic WAFs |
| Tier 3 fetch | `playwright` + `playwright-stealth` | for JS-rendered + cf-challenge sites |
| Tier 4 fetch | FlareSolverr (opt-in via env) | last resort when stealth isn't enough |
| Parse | `selectolax` + `trafilatura` + `markdownify` | fast DOM + good main-content extraction |
| Media | `httpx` streamed + `yt-dlp` for embeds + `Pillow` for dims | covers most of what you'd want |
| Concurrency | `asyncio` + `aiolimiter` per-domain caps | single process, plays nice with Textual |
| State | `aiosqlite` ledger | resumable jobs, resumable crawls |
| Logging | `structlog` → Rich console / JSON file | one source of truth for CLI + TUI |

Each tier is opt-in via flags (`--tier 1|2|3|4|auto`). The escalator handles the typical case: try tier 1, watch for cf-challenge markers / 403 / 503 / Turnstile, climb a tier, repeat.

## output layout (per scraped URL)

```
<out_root>/<domain>/<slug>/
  content.md         # main content via trafilatura → markdownify, YAML frontmatter
  metadata.json      # title, og:*, twitter:*, jsonld, http headers, fetch tier, timing
  assets.json        # every <img>/<video>/<audio>/<source>/<iframe-embed> + sha256 + local_path
  links.json         # internal + external links with anchor text + rel attrs
  assets/
    images/<sha256>.<ext>
    videos/<sha256>.<ext>
    audio/<sha256>.<ext>
  raw.html           # only with --keep-html
```

Crawl mode adds these per domain:

- `_index.md` — auto TOC across pages we fetched
- `_sitemap.md` + `_sitemap.json` — discovered graph (parent → child, with ✓/✗/↷ badges and orphans)
- `_site.sqlite` — the frontier, so I can `gimmethatdata resume` after Ctrl-C

`.ignore/runs/<job-id>/` holds the structured JSON logs (gitignored).

## repo layout

```
gimmethatdata/
├── pyproject.toml          # uv-managed, deps + ruff/mypy/pytest config
├── uv.lock                 # committed
├── masterplan.md           # this file
├── README.md
├── .gitignore
├── .ignore/                # gitignored: dev journal + run artifacts
├── src/gimmethatdata/
│   ├── __init__.py, __main__.py, cli.py, config.py, logging_setup.py
│   ├── core/               # models, pipeline, runner, url_utils
│   ├── fetch/              # tier1..4, escalator, proxy, rate_limit, headers, robots, factory
│   ├── parse/              # extractor, markdown, assets, metadata, plugins, presets, ocr
│   ├── crawl/              # frontier, sitemap (xml/robots seed), sitemap_writer, crawler
│   ├── media/              # downloader, ytdlp_adapter
│   ├── persist/            # writer, ledger, index
│   ├── export/             # pdf
│   └── tui/                # app + screens/ (home, new_job, progress, inspector) + log_bridge
└── tests/
    ├── unit/
    └── integration/
```

## install

```bash
# baseline
uv sync

# one-shot: extras + chromium + verify it actually launches + doctor
uv run gimmethatdata setup

# or piecewise
uv sync --extra bypass --extra media --extra state --extra pdf
uv run playwright install chromium
```

## commands

| command | what it does |
| --- | --- |
| `scrape <urls...>` | per-page or batch (with `--urls-file`, `--job-id`, `--preset`, `--tier`, `--proxy`...) |
| `crawl <seed>` | full-site crawl (depth + max-pages + scope + sitemap.xml seed) |
| `resume <job-id>` | continue from where Ctrl-C left it |
| `sitemap <domain-dir>` | (re)build `_sitemap.json` + `_sitemap.md` from `_site.sqlite` |
| `export-pdf <path>` | single PDF of every `content.md` under `<path>` with embedded images + media badges |
| `tui` | launch the Textual app |
| `setup` / `doctor` | one-shot install / diagnose without touching anything |
| `config` | print resolved settings |

## status

The CLI + TUI both work end-to-end. Tested against `udaysinh.me` (28 pages discovered + crawled + exported to a 3.9 MB PDF). All checks pass:

- `uv run ruff check .`
- `uv run mypy`
- `uv run pytest -q`

## ideas for later

- Distributed mode (redis-backed frontier across machines).
- LLM-assisted content cleanup hook (opt-in, off by default).
- Plugin extractors for the big sites (Reddit, Wikipedia, Twitter exports) shipped as separate packages.
- Better viewer for the TUI inspector (asset preview pane, sitemap tree view).
- Browser extension that pushes URLs into the queue from the page you're on.

## license

See `LICENSE`.
