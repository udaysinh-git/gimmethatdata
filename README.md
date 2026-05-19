<h1 align="center">
  <img src="assets/logo.png" alt="gimmethatdata mascot" width="180" /><br/>
  gimmethatdata
</h1>

<p align="center">
  <em>All-in-one async web scraper with a Textual TUI. Built in Python, managed by <code>uv</code>.</em>
</p>

<p align="center">
  <a href="#"><img alt="status" src="https://img.shields.io/badge/status-alpha-orange" /></a>
  <a href="#"><img alt="python" src="https://img.shields.io/badge/python-3.11%2B-blue" /></a>
  <a href="https://docs.astral.sh/uv/"><img alt="managed by uv" src="https://img.shields.io/badge/managed%20by-uv-261230" /></a>
</p>

<p align="center">
  <img src="assets/banner.png" alt="gimmethatdata banner" width="640" />
</p>

Scrape any site — single page, selected pages, or entire site — into clean Markdown with full asset manifests (images, videos, embeds, links, tags). Tiered anti-bot bypass. Proxy-aware. Async concurrency. Resume support.

## Quickstart

```bash
# first time only — install gimmethatdata + dev deps
uv sync

# one-shot: extras + chromium download + a real launch test + doctor
uv run gimmethatdata setup
#   --full         also install the OCR extra
#   --no-browsers  skip the chromium download
#   --skip-sync    only run browser install + doctor

# scrape a single page
uv run gimmethatdata scrape https://example.com --out ./out

# crawl an entire site (depth + page-count caps; --include-subdomains seeds from crt.sh)
uv run gimmethatdata crawl https://example.com --depth 2 --max-pages 50

# scrape behind a login (basic / bearer / cookies / arbitrary headers)
uv run gimmethatdata scrape https://api.example.com/dashboard \
  --auth bearer:eyJhbGc... \
  --cookie "sid=abc123" \
  -H "X-Org-Id: 42"

# turn on the on-disk HTTP cache so re-runs of the same URLs are free
uv run gimmethatdata scrape https://example.com --cache-dir .ignore/cache

# watch a site every hour and diff each run against the previous
uv run gimmethatdata watch https://example.com --every 1h --mode crawl --depth 1

# compare two scrape snapshots
uv run gimmethatdata diff ./out/yesterday ./out/today --out diff.md

# search every page you've ever scraped (sqlite FTS5)
uv run gimmethatdata search "embedding model" --out ./out --reindex

# discover subdomains via Certificate Transparency
uv run gimmethatdata subdomains example.com

# archive an Instagram profile (posts + reels + optional highlights + comment insights)
uv run gimmethatdata instagram udaysinh --pdf
#   --login <user> / --session-file <path>   needed for comments, highlights, stories
#   --limit 25                                stop after N posts (handy for sanity runs)
#   --no-analyze-comments                     skip the insights report

# export everything you've scraped to a PDF (images embedded, video links badged)
uv run gimmethatdata export-pdf ./out/example.com --out report.pdf

# launch the TUI (Home · NewJob · Progress · Inspector · Search · Sitemap · Diff · Settings)
uv run gimmethatdata tui

# diagnose what's installed without changing anything
uv run gimmethatdata doctor
```

See [masterplan.md](./masterplan.md) for the full design and command reference.

## Why?

- **One tool, three modes.** Per-page, multi-URL, full-site — same CLI, same output schema.
- **Anti-bot built in.** Tiered escalation: fast HTTP → TLS-fingerprinted client → headless stealth browser → optional FlareSolverr.
- **Proxy-aware.** Single proxy, rotating pool, sticky-per-domain.
- **Markdown-first.** Main content via trafilatura → markdownify, with the full asset manifest sitting next to it.
- **Resumable.** SQLite-backed ledger; Ctrl-C and rerun whenever.
- **Own sitemap.** Crawl mode builds a discovered graph (`_sitemap.json` + tree-rendered `_sitemap.md`) from the links it actually walked.
- **PDF export.** Bundle any folder of scraped pages into a single PDF — cover, TOC, embedded images, badged media links.
- **Auth + HTTP cache.** Basic, Bearer, cookies file, arbitrary headers. On-disk cache via ETag / Last-Modified.
- **Watch + diff.** Re-scrape on an interval, emit only what changed. Stand-alone `diff` command works on any two snapshots.
- **Full-text search.** SQLite FTS5 across every scraped page. CLI command + TUI screen with live preview.
- **Subdomain enumeration.** Optional crt.sh seeding before a crawl.
- **PDF input.** Point it at a PDF URL — text + metadata get the same `content.md` / `metadata.json` treatment as an HTML page.
- **Real TUI.** Textual screens for jobs, progress, inspector, search, live sitemap tree, diff view, and a settings editor.

## License

See [LICENSE](./LICENSE).
