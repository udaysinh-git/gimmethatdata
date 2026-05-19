<h1 align="center">
  <img src="../assets/logo.png" alt="gimmethatdata mascot" width="120" /><br/>
  gimmethatdata · complete reference
</h1>

<p align="center">
  <img src="../assets/banner.png" alt="gimmethatdata banner" width="640" />
</p>

Every command, every flag, every TUI screen. Generated from the source — keep in sync when you add a feature.

> Looking for a short overview? See the [README](../README.md).
> Looking for design rationale? See [masterplan.md](../masterplan.md).

---

## Table of contents

1. [Install + first run](#install--first-run)
2. [Output layout](#output-layout)
3. [Global flags](#global-flags)
4. [Commands](#commands)
   - [scrape](#scrape)
   - [crawl](#crawl)
   - [resume](#resume)
   - [watch](#watch)
   - [diff](#diff)
   - [search](#search)
   - [sitemap](#sitemap)
   - [subdomains](#subdomains)
   - [export-pdf](#export-pdf)
   - [Instagram suite](#instagram-suite)
   - [setup · doctor · config](#setup--doctor--config)
5. [TUI screens](#tui-screens)
6. [Extension points](#extension-points)
7. [Configuration file](#configuration-file)
8. [Environment variables](#environment-variables)
9. [Troubleshooting](#troubleshooting)

---

## Install + first run

```bash
git clone https://github.com/udaysinh-git/gimmethatdata
cd gimmethatdata
uv sync                          # baseline
uv run gimmethatdata setup       # installs extras, downloads chromium, verifies it
uv run gimmethatdata doctor      # any time you want a sanity check
```

Python 3.11+. Tested on Windows 11, macOS 14, Ubuntu 24.04.

Install extras à la carte if you don't want everything:

| extra | adds | needed by |
| --- | --- | --- |
| `bypass` | `curl_cffi`, `playwright`, `playwright-stealth` | fetch tiers 2 + 3 + 4 (and PDF export's chromium) |
| `media` | `yt-dlp`, `Pillow`, `pypdf` | video downloads + image dims + PDF input |
| `state` | `aiosqlite` | resumable jobs + crawl frontier |
| `pdf` | `markdown` | `export-pdf` |
| `ocr` | `pytesseract` (needs Tesseract installed at OS level) | `--ocr` / `--ocr-images` |
| `instagram` | `instagrapi` | the IG suite |
| `all` | everything above | — |

---

## Output layout

Per scraped URL:

```
<out>/<domain>/<slugified-path>/
  content.md            # main content via trafilatura → markdownify, YAML frontmatter
  metadata.json         # title, lang, og:*, twitter:*, jsonld, headings, headers, fetch tier, timing
  assets.json           # every <img>/<video>/<audio>/<source>/<iframe>/media-link + sha256 + local path
  links.json            # internal + external links with anchor text + rel attrs
  assets/
    images/<sha256>.<ext>
    videos/<sha256>.<ext>
    audio/<sha256>.<ext>
  raw.html              # only with --keep-html
```

Crawl mode also writes per domain:

- `_index.md` — auto TOC across pages
- `_sitemap.md` + `_sitemap.json` — discovered graph (parent → child, with status badges)
- `_site.sqlite` — frontier ledger (resumable)

Run-time artifacts (gitignored):

- `<out>/_jobs.sqlite` — multi-URL job ledger
- `<out>/_search.sqlite` — FTS index
- `.ignore/runs/<job-id>/` — structured JSON logs

---

## Global flags

Available on every command:

| flag | what |
| --- | --- |
| `--verbose` / `-v` | DEBUG-level logs |
| `--quiet` / `-q` | only error output |
| `--version` | print version + exit |
| `--help` | command-scoped help |

---

## Commands

### `scrape`

Scrape one or more URLs.

```bash
gimmethatdata scrape <url1> [url2 ...] [OPTIONS]
gimmethatdata scrape --urls-file urls.txt [OPTIONS]
```

| flag | default | what |
| --- | --- | --- |
| `URLS` | — | positional URLs (any number; can be combined with `--urls-file`) |
| `--urls-file PATH` | — | newline-delimited URL list (`#` comments allowed) |
| `--job-id NAME` | timestamped | reusable job id (works with `resume`) |
| `--out / -o DIR` | `out` | output root |
| `--download-images` | off | download every image into `assets/images/` |
| `--download-videos` | off | use yt-dlp for embedded YouTube/Vimeo/Twitch/Dailymotion |
| `--download-audio` | off | download `<audio>` sources |
| `--asset-types csv` | — | overrides the `--download-*` flags (`image,video,audio`) |
| `--max-asset-mb N` | `50` | per-asset size cap |
| `--max-total-mb N` | `2048` | per-job total asset budget |
| `--keep-html` | off | persist `raw.html` alongside `content.md` |
| `--timeout N` | `30` | per-request timeout (seconds) |
| `--tier {auto,1,2,3,4}` | `auto` | force a fetch tier; `auto` runs the escalator |
| `--proxy URL` | — | single proxy (`http://user:pass@host:port`) |
| `--rate-limit N` | `2.0` | requests per second per domain |
| `--auth basic:user:pass` | — | HTTP basic auth |
| `--auth bearer:<token>` | — | Bearer token |
| `--cookie "k=v"` | repeatable | one cookie pair or full `Cookie:` header value |
| `--cookies-file PATH` | — | Netscape `cookies.txt` file |
| `-H / --header "Name: Value"` | repeatable | extra request headers |
| `--cache-dir DIR` | — | on-disk HTTP cache (`ETag` / `Last-Modified`) |
| `--respect-robots` / `--ignore-robots` | `respect` | honor `robots.txt` |
| `--preset {vanilla,obsidian,logseq}` | `vanilla` | output preset |
| `--ocr` | off | run Tesseract over downloaded photos |

#### Examples

```bash
# Single page with full asset capture + raw HTML
gimmethatdata scrape https://blog.example.com/post -o ./out --download-images --keep-html

# Force tier 3 (Playwright) for a JS-heavy SPA
gimmethatdata scrape https://app.example.com --tier 3

# Auth + cache for repeat runs against an API-style site
gimmethatdata scrape https://api.example.com/dashboard \
  --auth bearer:eyJhbGc... \
  -H "X-Org-Id: 42" \
  --cache-dir .ignore/cache

# 50 URLs from a file, resumable, Obsidian preset
gimmethatdata scrape --urls-file urls.txt --preset obsidian --job-id batch-2026-05

# PDF URL — text extracted via pypdf, lands in the same layout
gimmethatdata scrape https://arxiv.org/pdf/2403.04132.pdf --out ./out
```

### `crawl`

Walk an entire site.

```bash
gimmethatdata crawl <seed-url> [OPTIONS]
```

| flag | default | what |
| --- | --- | --- |
| `URL` | — | seed URL (positional) |
| `--out / -o DIR` | `out` | output root |
| `--depth / -d N` | `2` | max link-walk depth |
| `--max-pages N` | `100` | hard cap on pages fetched |
| `--scope {same-domain,same-host,allowlist}` | `same-domain` | scope rule |
| `--allow PATTERN` | repeatable | glob/regex URLs must match (allowlist mode) |
| `--deny PATTERN` | repeatable | glob/regex URLs must NOT match |
| `--use-sitemap` / `--no-sitemap` | on | seed frontier from `sitemap.xml` |
| `--include-subdomains` | off | also seed from crt.sh-discovered subdomains |
| `--tier`, `--proxy`, `--rate-limit`, `--timeout` | same defaults | see `scrape` |
| `--respect-robots` / `--ignore-robots` | `respect` | |
| `--yes / -y` | off | skip the heavy-mode confirmation when `max-pages > 1000` |

Crawl mode writes `_index.md`, `_sitemap.md`, `_sitemap.json`, `_site.sqlite` under `<out>/<domain>/`.

#### Examples

```bash
# Quick 50-page survey
gimmethatdata crawl https://example.com --depth 2 --max-pages 50

# Whole eTLD+1 including subdomains, scoped tight
gimmethatdata crawl https://example.com --include-subdomains --scope same-domain --max-pages 500

# Allowlist crawl for a documentation site
gimmethatdata crawl https://docs.example.com \
  --scope allowlist \
  --allow "https://docs.example.com/api/*" \
  --deny "https://docs.example.com/api/private/*"
```

### `resume`

Resume an interrupted scrape job.

```bash
gimmethatdata resume <job-id> [OPTIONS]
```

| flag | default | what |
| --- | --- | --- |
| `JOB_ID` | — | job id (positional; from the original run's output) |
| `--out / -o DIR` | `out` | where `_jobs.sqlite` lives |
| `--retry-failed` | off | also retry pages that previously failed |
| `--timeout / --tier / --proxy / --rate-limit / --respect-robots` | same defaults | |

### `watch`

Re-scrape a URL or crawl a seed on an interval; auto-diff each tick.

```bash
gimmethatdata watch <url> [OPTIONS]
```

| flag | default | what |
| --- | --- | --- |
| `URL` | — | target URL (positional) |
| `--every DURATION` | `1h` | `30s` / `5m` / `1h` / `12d` |
| `--mode {scrape,crawl}` | `scrape` | per-tick action |
| `--iterations / -n N` | infinite | stop after N ticks |
| `--out / -o DIR` | `watch` | snapshot root |
| `--depth N` | `1` | crawl depth (mode=crawl) |
| `--max-pages N` | `50` | crawl page cap (mode=crawl) |

Each tick lands in `<out>/<timestamp>/`; if a previous snapshot exists, `_diff.md` is written automatically.

### `diff`

Compare two scrape snapshots.

```bash
gimmethatdata diff <before-dir> <after-dir> [OPTIONS]
```

| flag | default | what |
| --- | --- | --- |
| `--out / -o PATH` | stdout | write report to this Markdown file |

Output: `added` / `removed` / `changed` page tables + unified diff per changed page.

### `search`

SQLite FTS5 full-text search across every scraped `content.md`.

```bash
gimmethatdata search "<query>" [OPTIONS]
```

| flag | default | what |
| --- | --- | --- |
| `QUERY` | — | FTS query (phrases + multi-word work) |
| `--out / -o DIR` | `out` | out-root holding scraped pages |
| `--reindex` | off | rebuild the FTS index first |
| `--limit N` | `25` | max hits to print |

Index lives at `<out>/_search.sqlite`.

### `sitemap`

(Re)build `_sitemap.json` + `_sitemap.md` from a crawl's `_site.sqlite`.

```bash
gimmethatdata sitemap <domain-dir> [--seed URL]
```

### `subdomains`

Discover subdomains via Certificate Transparency (crt.sh).

```bash
gimmethatdata subdomains <domain> [--max N]
```

### `export-pdf`

Bundle scraped pages into a single PDF.

```bash
gimmethatdata export-pdf <path> [OPTIONS]
```

| flag | default | what |
| --- | --- | --- |
| `PATH` | — | single page dir, domain dir, or any folder with `content.md`s underneath |
| `--out / -o FILE` | `<path>/export.pdf` | PDF path |
| `--title T` | derived | document title |
| `--page-size {A4,Letter,Legal,A3,A5}` | `A4` | |
| `--keep-html` | off | leave the intermediate `_export.html` alongside the assets |

Rendered via headless chromium (`bypass` extra). Embeds images locally; videos and embeds become badged links.

### Instagram suite

Powered by [instagrapi](https://github.com/subzeroid/instagrapi). Requires the `instagram` extra.

#### `instagram`

```bash
gimmethatdata instagram <handle[,handle2,...]> [OPTIONS]
gimmethatdata instagram --users-file handles.txt [OPTIONS]
```

| flag | default | what |
| --- | --- | --- |
| `USERNAME` | — | handle (or comma-separated list); `--users-file` extends the list |
| `--out / -o DIR` | `out` | output root |
| `--login USER` | — | login as this username |
| `--password PASS` | (prompt) | for `--login` |
| `--session-file PATH` | — | preferred — load / save instagrapi settings |
| `--verification-code CODE` | — | 6-digit 2FA code |
| `--posts` / `--no-posts` | on | |
| `--reels` / `--no-reels` | on | |
| `--highlights` | off | needs login |
| `--stories` | off | needs login |
| `--tagged` | off | posts where user was tagged by others |
| `--comments` / `--no-comments` | on (auto-off when anonymous) | |
| `--likers` | off | save list of users who liked each post (login) |
| `--comment-replies` | off | fetch nested replies (slower) |
| `--enrich-locations` | off | resolve geotag pks → lat/lng/address |
| `--ocr-images` | off | OCR every downloaded photo |
| `--since YYYY-MM-DD` | — | incremental — skip older posts |
| `--no-resume` | off | re-download shortcodes already on disk |
| `--limit N` | — | cap posts per profile |
| `--download-images` / `--no-download-images` | on | |
| `--analyze-comments` / `--no-analyze-comments` | on | build comment-insights report |
| `--analytics` / `--no-analytics` | on | build engagement report |
| `--contact-sheet` | off | generate `_contact_sheet.html` |
| `--pdf` | off | auto-export the whole profile to PDF |

Output (per profile):

```
<out>/instagram/<user>/
  profile.json                    bio + counts
  posts/<shortcode>/              content.md + metadata + assets + comments + (likers.json)
  reels/<shortcode>/              cover frame only (no video bodies)
  tagged/<shortcode>/             posts tagging this user
  highlights/<title>/<id>/        (opt-in)
  stories/<id>/                   (opt-in)
  _comments_report.{md,json}      top commenters / hashtags / mentions / emojis / busiest posts / timeline
  _engagement_report.{md,json}    avg likes, reels-vs-photos, leaderboards, posting heatmap, daily engagement
  _contact_sheet.html             (with --contact-sheet)
  <user>.pdf                      (with --pdf)
```

#### `ig-hashtag`

```bash
gimmethatdata ig-hashtag <tag> [--sort top|recent] [--amount N] [--session-file PATH]
```

Archives top/recent posts for a hashtag under `<out>/instagram/hashtags/<tag>/`.

#### `ig-location`

```bash
gimmethatdata ig-location <location_pk> [--sort top|recent] [--amount N] [--session-file PATH]
```

#### `ig-music`

```bash
gimmethatdata ig-music <track_id> [--amount N] [--session-file PATH]
```

#### `ig-compare`

```bash
gimmethatdata ig-compare <left-profile-dir> <right-profile-dir> [--out DIR]
```

Side-by-side metric deltas + commenter overlap (Jaccard) + shared hashtags/mentions. Writes `_compare-<a>-vs-<b>.{md,json}`.

#### `ig-engagement`

```bash
gimmethatdata ig-engagement <profile-dir>
```

Rebuild `_engagement_report.{md,json}` from existing data on disk.

#### `ig-contact-sheet`

```bash
gimmethatdata ig-contact-sheet <profile-dir> [--out FILE]
```

Render every downloaded image into one browsable HTML grid with badges + captions.

#### `ig-import-cookie`

```bash
gimmethatdata ig-import-cookie <username> --sessionid <cookie> --session-file <path>
```

Mint an instagrapi session file from a browser `sessionid` cookie. Use when password login keeps tripping IG's challenge flow.

### `setup` · `doctor` · `config`

```bash
gimmethatdata setup [--full] [--no-browsers] [--skip-sync]
gimmethatdata doctor                  # non-destructive diagnose
gimmethatdata config                  # print resolved settings
```

`setup` runs 4 steps: `uv sync --extra ...` → `playwright install chromium` (with `--with-deps` on Linux) → launch chromium to verify it works → doctor report.

---

## TUI screens

Launch with:

```bash
gimmethatdata tui [--out DIR]
```

### Global bindings

| key | action |
| --- | --- |
| `n` | New job |
| `s` | Search |
| `m` | Live sitemap |
| `d` | Diff |
| `i` | Instagram dashboard |
| `,` | Settings |
| `?` | Help notification |
| `q` | Quit |

### Home

Lists recent jobs from `<out>/_jobs.sqlite`. Bindings: `n` new · `r` refresh · `Enter` inspect · `Esc` back.

### NewJob

Form for a single scrape/crawl job. Fields:

- **Mode** — radio: Single page / Selected URLs / Full-site crawl.
- **URLs** — one or whitespace-separated.
- **Checkboxes** — download-images, download-videos, respect-robots.
- **Crawl** — max depth, max pages.
- **Buttons** — Submit (Ctrl+S) · Cancel (Esc).

Submitting pushes `ProgressScreen`.

### Progress

Live job execution. Shows:

- Job banner + target URL.
- `ProgressBar` driven by `JobEvent` (started → page_done/page_failed → finished).
- `done / failed / total` counter.
- `RichLog` streaming structlog output (via `tui/log_bridge.TUILogSink`).
- Buttons — Cancel (`c`) cancels the worker; Back (`b`) cancels + pops the screen.

### Inspector

Opens from Home → Enter on a job row.

- Left: DataTable of done pages for the selected job (URL · tier · updated).
- Right: `MarkdownViewer` previews `content.md`.
- Bottom: `DirectoryTree` of `out_root`.
- Press `e` (or Export PDF button) → exports the job's domain dir to PDF in a background worker.

### Search

Global FTS across every scraped `content.md`.

- Input field + Search button + Reindex button.
- Hit table (title · snippet preview with `[match]` markers).
- Click a row → preview pane loads that page's `content.md`.

Bindings: `Enter` search · `Ctrl+R` reindex · `Esc` back.

### LiveSitemap

Polls `<domain>/_site.sqlite` every 2 s and renders the discovery graph as a `Tree` with ✓ / ✗ / ↷ / … status badges. The crawl can be running concurrently — the tree grows live.

Bindings: `r` refresh now · `Esc` back.

### Diff

Two paths in (before / after), Compute → DataTable of changes (+ added · − removed · ~ changed). Click a row → unified diff in the right pane.

### Settings

Form-driven editor for `gimmethatdata.toml` (concurrency, fetch timeout, user-agent, crawl depth/pages, respect-robots, verify-tls). Save with `Ctrl+S`.

### Instagram dashboard (binding `i`)

Three-pane browser for archived IG profiles.

- **Left** — accounts under `<out>/instagram/` (excluding `hashtags/`, `locations/`, `music/`).
- **Middle** — posts/reels/tagged for the selected account.
- **Right** — `TabbedContent` with:
  - **Content** — `content.md` of the selected post.
  - **Comments** — indented thread (top-level + replies if present).
  - **Engagement** — `_engagement_report.md` of the current account.

Bindings: `n` New IG job · `d` Discovery · `c` Compare · `g` rebuild reports · `r` refresh · `Esc` back.

### Instagram NewJob

Form for IG archive with every flag the CLI has:

- Handle (or comma-separated multi).
- Session file path or login user.
- Toggles: posts / reels / highlights / stories / tagged.
- Toggles: comments / likers / comment-replies / enrich-locations / OCR.
- Toggles: engagement report / contact sheet / PDF / resume.
- Limit (cap N) and Since (YYYY-MM-DD).

Runs in a Textual worker; streams structlog into a `RichLog`.

### Instagram Discovery

Hashtag / Location / Music seed runs from the TUI. Radio for kind + sort, amount, session-file path.

### Instagram Compare

Two profile dirs in, render `_compare-...md` inline via `MarkdownViewer`.

---

## Extension points

### Custom extractors

Register a Python entry point under group `gimmethatdata.extractors`:

```toml
# pyproject.toml of your plugin package
[project.entry-points."gimmethatdata.extractors"]
my_site = "my_pkg.extractor:get_extractor"
```

Your factory returns an object satisfying the `Extractor` protocol:

```python
from gimmethatdata.parse.plugins import ExtractedDocument

class MySiteExtractor:
    name = "mysite"
    def matches(self, url: str) -> bool: ...
    def extract(self, html: str, *, url: str) -> ExtractedDocument | None: ...
```

The pipeline tries plugins first, falls through to trafilatura.

### Output presets

`--preset vanilla | obsidian | logseq` selects how `content.md` is rendered:

- `vanilla` — YAML frontmatter + plain Markdown body.
- `obsidian` — frontmatter with `tags: [gimmethatdata/<domain>, lang/<code>]`; internal links rewritten to `[[abs_url|anchor]]`.
- `logseq` — `- # title` top-level block + `key:: value` properties + indented body.

---

## Configuration file

`gimmethatdata.toml` in the project root (or `~/.config/gimmethatdata/config.toml`) overrides defaults.

```toml
concurrency = 8

[fetch]
timeout_seconds = 30
user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ..."
per_domain_rps = 2.0
verify_tls = true
follow_redirects = true

[crawl]
max_depth = 2
max_pages = 100
respect_robots = true
same_domain_only = true

[media]
download_images = false
download_videos = false
max_asset_mb = 50
asset_types = ["image"]
```

Resolution order (later overrides earlier):

1. Built-in defaults.
2. `~/.config/gimmethatdata/config.toml`.
3. `./gimmethatdata.toml`.
4. `GIMMETHATDATA_*` env vars (nested with `__`, e.g. `GIMMETHATDATA_FETCH__TIMEOUT_SECONDS=60`).
5. CLI flags.

Editable from the TUI via the Settings screen.

---

## Environment variables

| var | purpose |
| --- | --- |
| `GIMMETHATDATA_*` | override any settings field (see Configuration above) |
| `FLARESOLVERR_URL` | enable tier-4 FlareSolverr fetcher (`http://localhost:8191` typical) |
| `PYTHONIOENCODING=utf-8` | safety belt on Windows shells that default to cp1252 |

---

## Troubleshooting

| symptom | what to do |
| --- | --- |
| **Playwright `Executable doesn't exist at ...chrome-headless-shell.exe`** | Run `gimmethatdata setup` — that downloads chromium + verifies launch. |
| **`Unexpected null login result` on `instagram --login`** | IG flagged the device. Open the IG app on a known device, accept the prompt, retry. Or use `gimmethatdata ig-import-cookie` with a browser `sessionid`. |
| **`profile lookup failed for @<user>`** anonymous | Instagram blocks anonymous GraphQL across the board now. Use `--session-file`. |
| **Crawl returns 403/503 everywhere** | Force tier 3: `--tier 3`. If still failing, set `FLARESOLVERR_URL` and use `--tier 4`. |
| **Windows charmap encoding crash** | Set `PYTHONIOENCODING=utf-8` or use Windows Terminal (UTF-8 by default). |
| **TUI freezes during a long crawl** | The worker is single-process — that's expected. Heavy crawls should run via the CLI; use the TUI to inspect afterwards. |
| **`_search.sqlite` returns no hits** | Re-run with `--reindex`. The index isn't auto-rebuilt as new pages land. |
| **OCR appended nothing** | Tesseract isn't installed at OS level. macOS: `brew install tesseract`. Windows: install from UB Mannheim. Ubuntu: `apt install tesseract-ocr`. |

If you hit something not listed, run `gimmethatdata doctor` first — it surfaces the most common missing-tool cases.
