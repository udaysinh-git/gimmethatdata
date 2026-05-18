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

# crawl an entire site (depth + page-count caps)
uv run gimmethatdata crawl https://example.com --depth 2 --max-pages 50

# export everything you've scraped to a PDF (images embedded, video links badged)
uv run gimmethatdata export-pdf ./out/example.com --out report.pdf

# launch the TUI
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
- **Real TUI.** Textual screens for browsing jobs, watching progress live, inspecting output, kicking off new runs.

## License

See [LICENSE](./LICENSE).
