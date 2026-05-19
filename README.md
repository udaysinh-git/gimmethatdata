<h1 align="center">
  <img src="assets/logo.png" alt="gimmethatdata mascot" width="180" /><br/>
  gimmethatdata
</h1>

<p align="center">
  <em>All-in-one async web scraper with a Textual TUI. Built in Python, managed by <code>uv</code>.</em>
</p>

<p align="center">
  <a href="https://github.com/udaysinh-git/gimmethatdata"><img alt="status" src="https://img.shields.io/badge/status-alpha-orange" /></a>
  <a href="https://www.python.org/downloads/"><img alt="python" src="https://img.shields.io/badge/python-3.11%2B-blue" /></a>
  <a href="https://docs.astral.sh/uv/"><img alt="managed%20by-uv" src="https://img.shields.io/badge/managed%20by-uv-261230" /></a>
  <a href="./docs/completeDocs.md"><img alt="docs" src="https://img.shields.io/badge/docs-completeDocs.md-7c3aed" /></a>
  <a href="https://github.com/udaysinh-git/gimmethatdata"><img alt="github" src="https://img.shields.io/badge/github-udaysinh--git%2Fgimmethatdata-181717?logo=github" /></a>
</p>

<p align="center">
  <img src="assets/banner.png" alt="gimmethatdata banner" width="780" />
</p>

Scrape any site — single page, selected pages, or entire crawl — into a clean folder of Markdown plus structured asset manifests (images, videos, embeds, links, tags). Tiered anti-bot bypass, proxy-aware, resumable, full-text searchable, PDF-exportable, and with a real Textual TUI on top. Plus a dedicated Instagram archiver with engagement insights.

> Full command + TUI reference: **[docs/completeDocs.md](./docs/completeDocs.md)**.
> Project design + roadmap: **[masterplan.md](./masterplan.md)**.

---

## Quickstart

```bash
# clone + install
git clone https://github.com/udaysinh-git/gimmethatdata
cd gimmethatdata
uv sync

# pull in extras + chromium + sanity-check
uv run gimmethatdata setup
#   --full   also installs OCR + Instagram extras

# scrape a single page
uv run gimmethatdata scrape https://example.com --out ./out

# crawl a whole site, with depth + budget caps
uv run gimmethatdata crawl https://example.com --depth 2 --max-pages 50

# launch the TUI (Home · NewJob · Progress · Inspector · Search · Sitemap · Diff · Settings · Instagram)
uv run gimmethatdata tui
```

---

## What's inside

### Scraping engine

- **Three modes**: single URL · multi-URL (with `--urls-file`) · full-site crawl.
- **4-tier fetch stack** with auto-escalation on cf-challenges, 403/429/503, Turnstile:
  - tier 1 — `httpx[http2]` (fast path)
  - tier 2 — `curl_cffi` with Chrome TLS fingerprint
  - tier 3 — `playwright` + `playwright-stealth` (JS-rendered + bot walls)
  - tier 4 — FlareSolverr shim (opt-in via env)
- **Auth** built in: `--auth basic:u:p`, `--auth bearer:tok`, `--cookie k=v`, `--cookies-file cookies.txt`, `-H "Name: Value"`.
- **HTTP cache** (`--cache-dir`) honors `ETag` / `Last-Modified` so re-runs are free.
- **Proxies** with rotation strategies: round-robin, sticky-per-domain, per-failure.
- **Per-domain rate limiter** + retry/backoff.
- **PDF input** — point it at a `.pdf` URL and it renders the text + metadata into the same `content.md` layout.

### Output layout (per page)

```
<out>/<domain>/<slug>/
  content.md         # main content via trafilatura → markdownify, YAML frontmatter
  metadata.json      # title, og:*, twitter:*, jsonld, headers, fetch tier, timing
  assets.json        # every <img>/<video>/<audio>/<source>/<iframe>/media link
  links.json         # internal + external links with anchor text
  assets/images/<sha256>.<ext>
  assets/videos/<sha256>.<ext>
  raw.html           # only with --keep-html
```

Crawl mode adds `_index.md`, `_sitemap.md`, `_sitemap.json`, `_site.sqlite` per domain.

### Crawling intelligence

- **Own sitemap** built from your crawl — discovered tree with ✓/✗/↷ badges; never just blindly trusts `sitemap.xml`.
- **`--include-subdomains`** seeds the frontier from Certificate Transparency (`crt.sh`).
- **Scope rules**: `same-domain`, `same-host`, glob `--allow` / `--deny` lists.
- **Resumable** — Ctrl-C anywhere, rerun with `gimmethatdata resume <job-id>`.
- **Heavy guardrails** — `>1000` pages prompts before crawling.

### Output formats

- **Markdown** (default) — `content.md` per page.
- **Output presets**: `--preset vanilla|obsidian|logseq` (Obsidian wiki-links, Logseq blocks).
- **PDF bundle**: `gimmethatdata export-pdf <path>` — embedded images, badged media links, cover, TOC. Renders via headless chromium.
- **HTML contact sheet** (Instagram): every photo in a card grid.

### Watch + diff + search

- **`watch`** — periodic re-scrape with `--every 1h`, auto-diff against the previous snapshot.
- **`diff`** — added / removed / changed pages between two snapshots, unified diffs inline.
- **`search`** — SQLite FTS5 full-text across every scraped page, with snippet highlights. CLI + TUI screen.

### Plugin extractors

Site-specific extractors registered via `entry_points = "gimmethatdata.extractors"`. Built-in: **Reddit** (`/r/<sub>/comments/...` + subreddit listings → indented comment trees via the public JSON endpoint).

### Optional OCR

`--ocr` runs `pytesseract` over downloaded images and appends an `## OCR` section to `content.md`. Needs the `ocr` extra and Tesseract installed at OS level.

---

## Instagram archiver

Dedicated CLI + TUI surface for Instagram, powered by [instagrapi](https://github.com/subzeroid/instagrapi) (mobile private API — way more reliable than the web scrape path that died in 2024).

```bash
# anonymous-ish (very limited — IG blocks most public lookups now)
uv run gimmethatdata instagram <user>

# preferred: mint a session once, reuse it for weeks
uv run instaloader --login=<your_handle> --sessionfile .ignore/ig-session   # or our ig-import-cookie
uv run gimmethatdata instagram <target> --session-file .ignore/ig-session --pdf --contact-sheet
```

Per-profile output:

```
<out>/instagram/<user>/
  profile.json               # bio + counts
  posts/<shortcode>/         # content.md + metadata + assets + comments + likers
  reels/<shortcode>/         # cover frame only (no video bodies)
  tagged/<shortcode>/        # posts where the user was tagged by others
  highlights/<title>/<id>/   # opt-in
  stories/<id>/              # opt-in
  _comments_report.{md,json}     # top commenters, hashtags, emojis, timeline
  _engagement_report.{md,json}   # avg likes, reels-vs-photos, heatmap, leaderboards
  _contact_sheet.html            # browsable grid of all images
```

Plus standalone commands: `ig-hashtag`, `ig-location`, `ig-music`, `ig-compare` (audience overlap + Jaccard), `ig-engagement` (rebuild reports), `ig-contact-sheet`, `ig-import-cookie`.

---

## TUI

```bash
uv run gimmethatdata tui
```

Top-level keys: `n` new job · `s` search · `m` sitemap · `d` diff · `i` instagram · `,` settings · `q` quit · `?` help.

Screens (see [completeDocs](./docs/completeDocs.md) for the full map):

- **Home** — recent jobs from the ledger, Enter to inspect.
- **NewJob** — fill in URLs + flags, watch the worker tick through.
- **Progress** — live event log + counters from a running job.
- **Inspector** — browse a job's pages; preview `content.md`; export to PDF inline (`e`).
- **Search** — FTS query + hit table + preview pane.
- **Sitemap** — live tree of the crawl frontier, polling `_site.sqlite`.
- **Diff** — two-pane snapshot compare.
- **Settings** — edit `gimmethatdata.toml` from the TUI.
- **Instagram** — 3-pane account / posts / preview with Content + Comments thread + Engagement tabs.
  - **IGNewJob** — form-driven IG archive with live event log.
  - **IGDiscovery** — hashtag / location / music seed runs.
  - **IGCompare** — pick two profile dirs, render compare in-place.

---

## Commands at a glance

| command | what |
| --- | --- |
| `scrape` | per-page or batch (`--urls-file`, `--job-id`, `--preset`, `--tier`, `--proxy`, `--auth`, `--cache-dir`, `--ocr` …) |
| `crawl` | full-site crawl (depth + page caps + scope + sitemap + `--include-subdomains`) |
| `resume` | continue a previously interrupted job |
| `watch` | periodic re-scrape + per-tick diff |
| `diff` | compare two snapshots |
| `search` | sqlite FTS5 full-text search |
| `sitemap` | (re)build `_sitemap.{md,json}` from `_site.sqlite` |
| `subdomains` | crt.sh enumeration |
| `instagram` | archive an IG profile (posts/reels/highlights/tagged/comments/likers/replies) |
| `ig-hashtag` / `ig-location` / `ig-music` | discovery archives |
| `ig-compare` / `ig-engagement` / `ig-contact-sheet` / `ig-import-cookie` | IG analytics + tooling |
| `export-pdf` | bundle scraped pages into a single PDF |
| `tui` | launch the Textual TUI |
| `setup` / `doctor` / `config` | install / diagnose / show resolved settings |

Run `uv run gimmethatdata <cmd> --help` on any of these for the full flag list, or jump to **[docs/completeDocs.md](./docs/completeDocs.md)** for the comprehensive reference.

---

## Install layers

```bash
uv sync                              # baseline scraper + dev deps
uv sync --extra bypass               # curl_cffi + playwright + stealth
uv sync --extra media                # yt-dlp + Pillow + pypdf
uv sync --extra state                # aiosqlite (resume / crawl frontier)
uv sync --extra pdf                  # markdown (export-pdf)
uv sync --extra ocr                  # pytesseract
uv sync --extra instagram            # instagrapi
uv sync --extra all                  # everything above
```

Or skip thinking about it and run `gimmethatdata setup` — that handles extras, downloads chromium, verifies it launches, and prints a doctor report.

---

## License

See [LICENSE](./LICENSE).
