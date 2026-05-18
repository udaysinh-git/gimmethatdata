"""Bundle scraped pages into a single PDF.

Walks the output for `content.md` files, renders them (+ asset manifests) into
one HTML doc with a cover and TOC, then hands the HTML to headless chromium
for printing. The temp HTML lives next to the assets so relative image paths
resolve.
"""

from __future__ import annotations

import contextlib
import html as html_lib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from gimmethatdata.core.models import utcnow
from gimmethatdata.logging_setup import get_logger

_log = get_logger(__name__)


@dataclass
class PageBundle:
    """One scraped page loaded back from disk for export."""

    output_dir: Path
    content_md: str
    metadata: dict[str, Any]
    assets: list[dict[str, Any]]
    links: list[dict[str, Any]]


def discover_pages(root: Path) -> list[PageBundle]:
    """Find every `content.md` under `root` and load its sibling JSON files."""
    if not root.exists():
        raise FileNotFoundError(f"export root does not exist: {root}")
    # Single-page case
    if (root / "content.md").exists():
        return [_load_page(root)]
    pages: list[PageBundle] = []
    for md_path in sorted(root.rglob("content.md")):
        pages.append(_load_page(md_path.parent))
    return pages


def _load_page(page_dir: Path) -> PageBundle:
    md = (page_dir / "content.md").read_text(encoding="utf-8")
    metadata = _safe_json(page_dir / "metadata.json", default={})
    assets = _safe_json(page_dir / "assets.json", default=[])
    links = _safe_json(page_dir / "links.json", default=[])
    return PageBundle(
        output_dir=page_dir,
        content_md=md,
        metadata=metadata if isinstance(metadata, dict) else {},
        assets=assets if isinstance(assets, list) else [],
        links=links if isinstance(links, list) else [],
    )


def _safe_json(path: Path, *, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _strip_frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---", 4)
    if end < 0:
        return text
    return text[end + 4 :].lstrip("\n")


def _md_to_html(md: str) -> str:
    try:
        import markdown
    except ImportError as exc:
        raise RuntimeError(
            "PDF export requires the `pdf` extra. Run "
            "`uv sync --extra pdf` or `gimmethatdata setup --full`."
        ) from exc
    rendered = markdown.markdown(
        md,
        extensions=["extra", "sane_lists", "toc", "tables", "fenced_code", "nl2br"],
        output_format="html",
    )
    return str(rendered)


_CSS = """
@page { size: A4; margin: 18mm 16mm; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
  font-size: 11pt;
  line-height: 1.55;
  color: #1f2328;
  max-width: 100%;
  margin: 0;
}
h1, h2, h3, h4 { line-height: 1.25; }
h1 { font-size: 22pt; border-bottom: 2px solid #d0d7de; padding-bottom: 0.2em; margin-top: 0; }
h2 { font-size: 16pt; border-bottom: 1px solid #eaecef; padding-bottom: 0.15em; margin-top: 1.4em; }
h3 { font-size: 13pt; color: #57606a; }
hr { border: none; border-top: 1px solid #eaecef; margin: 2em 0; }
p { margin: 0.6em 0; }
ul, ol { margin: 0.4em 0 0.8em 1.4em; }
li { margin: 0.15em 0; }
a { color: #0969da; text-decoration: none; }
a:hover { text-decoration: underline; }
code {
  font-family: ui-monospace, "Cascadia Code", Consolas, monospace;
  background: #f6f8fa; padding: 1px 5px; border-radius: 3px; font-size: 0.92em;
}
pre {
  background: #f6f8fa; padding: 12px; border-radius: 6px;
  overflow-x: auto; font-size: 9pt; line-height: 1.45;
}
pre code { background: none; padding: 0; }
img { max-width: 100%; height: auto; border-radius: 4px; margin: 8px 0; }
table { border-collapse: collapse; margin: 1em 0; }
th, td { border: 1px solid #d0d7de; padding: 6px 10px; text-align: left; }
th { background: #f6f8fa; }
blockquote {
  border-left: 3px solid #d0d7de; padding-left: 12px; margin-left: 0;
  color: #57606a;
}
.cover {
  page-break-after: always;
  display: flex; flex-direction: column; justify-content: center;
  min-height: 90vh; text-align: center;
}
.cover .title { font-size: 32pt; font-weight: 700; margin: 0.2em 0; }
.cover .domain { font-size: 16pt; color: #0969da; margin: 0.4em 0; }
.cover .meta { font-size: 11pt; color: #57606a; margin-top: 2em; }
.toc { page-break-after: always; }
.toc h2 { margin-top: 0; }
.toc ol { list-style: none; padding-left: 0; }
.toc li { padding: 4px 0; border-bottom: 1px dashed #eaecef; }
.toc .toc-num { display: inline-block; width: 2.2em; color: #6e7781; }
.toc .toc-url { font-size: 9pt; color: #6e7781; margin-left: 0.5em; }
.page-section { page-break-before: always; }
.page-section:first-of-type { page-break-before: auto; }
.page-meta {
  font-size: 9pt; color: #6e7781; margin-bottom: 1.2em;
  padding: 8px 12px; background: #f6f8fa; border-radius: 6px;
}
.page-meta .row { display: block; margin: 1px 0; }
.assets-block { margin-top: 2em; padding-top: 1em; border-top: 1px solid #eaecef; }
.assets-block h3 { font-size: 9pt; text-transform: uppercase; color: #6e7781; letter-spacing: 0.06em; margin-top: 1.4em; }
.image-grid { display: flex; flex-wrap: wrap; gap: 6px; }
.image-grid .thumb {
  display: flex; flex-direction: column; align-items: center;
  width: 140px;
}
.image-grid .thumb img {
  max-width: 140px; max-height: 140px; object-fit: cover;
  border: 1px solid #d0d7de;
}
.image-grid .thumb .cap {
  font-size: 7pt; color: #6e7781; word-break: break-all; margin-top: 2px;
  max-width: 140px;
}
.media-list { list-style: none; padding-left: 0; font-size: 9pt; }
.media-list li { padding: 3px 0; }
.badge {
  display: inline-block; padding: 1px 6px; border-radius: 3px;
  font-size: 8pt; font-weight: 600; margin-right: 5px; text-transform: uppercase;
}
.badge-image { background: #dafbe1; color: #1a7f37; }
.badge-video { background: #ffe4e6; color: #b3263c; }
.badge-audio { background: #fff8c5; color: #7d4e00; }
.badge-embed { background: #ddf4ff; color: #0550ae; }
"""


def _esc(text: str) -> str:
    return html_lib.escape(text or "")


def _format_meta(meta: dict[str, Any]) -> str:
    rows: list[str] = []
    url = meta.get("final_url") or meta.get("url") or ""
    if url:
        rows.append(
            f'<span class="row"><b>URL</b>: <a href="{_esc(url)}">{_esc(url)}</a></span>'
        )
    title = meta.get("title")
    if title:
        rows.append(f'<span class="row"><b>Title</b>: {_esc(str(title))}</span>')
    fetched = meta.get("fetched_at")
    tier = meta.get("tier")
    if fetched or tier:
        rows.append(
            f'<span class="row"><b>Fetched</b>: {_esc(str(fetched or "?"))} '
            f'<b style="margin-left:1em">Tier</b>: {_esc(str(tier or "?"))}</span>'
        )
    return "".join(rows)


def _format_assets(page: PageBundle) -> str:
    if not page.assets:
        return ""
    images: list[dict[str, Any]] = []
    videos: list[dict[str, Any]] = []
    audios: list[dict[str, Any]] = []
    embeds: list[dict[str, Any]] = []
    for asset in page.assets:
        kind = asset.get("kind")
        if kind == "image":
            images.append(asset)
        elif kind == "video":
            videos.append(asset)
        elif kind == "audio":
            audios.append(asset)
        elif kind == "embed":
            embeds.append(asset)

    parts: list[str] = ['<div class="assets-block"><h3>Assets</h3>']

    if images:
        parts.append('<h3>Images</h3><div class="image-grid">')
        for image in images:
            local = image.get("local_path")
            abs_url = image.get("abs_url", "")
            src = local if local else abs_url
            alt = image.get("alt") or ""
            parts.append(
                '<div class="thumb">'
                f'<a href="{_esc(abs_url)}"><img src="{_esc(src)}" alt="{_esc(alt)}"></a>'
                f'<span class="cap">{_esc(alt or abs_url)}</span>'
                "</div>"
            )
        parts.append("</div>")

    def _link_list(kind: str, items: list[dict[str, Any]], badge: str) -> None:
        if not items:
            return
        parts.append(f"<h3>{kind.title()}s</h3><ul class='media-list'>")
        for it in items:
            abs_url = it.get("abs_url", "")
            label = it.get("title") or it.get("alt") or abs_url
            parts.append(
                f'<li><span class="badge {badge}">{kind}</span>'
                f'<a href="{_esc(abs_url)}">{_esc(label)}</a></li>'
            )
        parts.append("</ul>")

    _link_list("video", videos, "badge-video")
    _link_list("audio", audios, "badge-audio")
    _link_list("embed", embeds, "badge-embed")

    parts.append("</div>")
    return "".join(parts)


def _page_section(index: int, page: PageBundle, *, html_root: Path) -> str:
    body_md = _strip_frontmatter(page.content_md)
    body_html = _md_to_html(body_md)
    # Rewrite image src/href that point at local paths so chromium can resolve
    # them relative to where the export HTML lives.
    rel = _relative_root(page.output_dir, html_root)
    body_html = _rewrite_local_paths(body_html, rel)
    assets_html = _format_assets(_rewrite_asset_paths(page, rel))
    anchor = f"page-{index}"
    return (
        f'<section class="page-section" id="{anchor}">'
        f'<h1>{_esc(page.metadata.get("title") or _short_url(page.metadata))}</h1>'
        f'<div class="page-meta">{_format_meta(page.metadata)}</div>'
        f"{body_html}"
        f"{assets_html}"
        "</section>"
    )


def _short_url(meta: dict[str, Any]) -> str:
    url = meta.get("final_url") or meta.get("url") or "Untitled"
    return str(url)


def _relative_root(page_dir: Path, html_root: Path) -> str:
    """Return a forward-slash prefix to prepend to relative paths from a page."""
    try:
        rel = page_dir.resolve().relative_to(html_root.resolve())
    except ValueError:
        return ""
    rel_str = str(rel).replace("\\", "/")
    return rel_str + "/" if rel_str and rel_str != "." else ""


def _rewrite_local_paths(html: str, rel_prefix: str) -> str:
    """Prepend `rel_prefix` to local `src="assets/..."` references in the HTML body."""
    if not rel_prefix:
        return html
    out = html
    for needle, replacement in (
        ('src="assets/', f'src="{rel_prefix}assets/'),
        ("src='assets/", f"src='{rel_prefix}assets/"),
        ('href="assets/', f'href="{rel_prefix}assets/'),
        ("href='assets/", f"href='{rel_prefix}assets/"),
    ):
        out = out.replace(needle, replacement)
    return out


def _rewrite_asset_paths(page: PageBundle, rel_prefix: str) -> PageBundle:
    if not rel_prefix:
        return page
    new_assets: list[dict[str, Any]] = []
    for asset in page.assets:
        local = asset.get("local_path")
        if local and not local.startswith(("http://", "https://", "/", rel_prefix)):
            asset = {**asset, "local_path": rel_prefix + local}
        new_assets.append(asset)
    return PageBundle(
        output_dir=page.output_dir,
        content_md=page.content_md,
        metadata=page.metadata,
        assets=new_assets,
        links=page.links,
    )


def _cover_and_toc(pages: list[PageBundle], *, title: str, source_root: Path) -> str:
    when = utcnow().strftime("%Y-%m-%d %H:%M UTC")
    cover = (
        f'<section class="cover">'
        f'<div class="title">{_esc(title)}</div>'
        f'<div class="domain">{_esc(source_root.name)}</div>'
        f'<div class="meta">Generated {when} · {len(pages)} pages</div>'
        f"</section>"
    )
    toc_items: list[str] = []
    for i, page in enumerate(pages, start=1):
        meta = page.metadata
        title_str = meta.get("title") or _short_url(meta)
        url = meta.get("final_url") or meta.get("url") or ""
        toc_items.append(
            f"<li>"
            f'<span class="toc-num">{i:>2}.</span>'
            f'<a href="#page-{i}">{_esc(str(title_str))}</a>'
            f'<span class="toc-url"> {_esc(str(url))}</span>'
            f"</li>"
        )
    toc = (
        '<section class="toc">'
        "<h2>Contents</h2>"
        f"<ol>{''.join(toc_items)}</ol>"
        "</section>"
    )
    return cover + toc


def build_html(pages: list[PageBundle], *, title: str, html_root: Path) -> str:
    """Compose the full export document."""
    sections = [
        _page_section(i, page, html_root=html_root)
        for i, page in enumerate(pages, start=1)
    ]
    return (
        "<!doctype html>"
        '<html lang="en">'
        "<head>"
        '<meta charset="utf-8">'
        f"<title>{_esc(title)}</title>"
        f"<style>{_CSS}</style>"
        "</head>"
        "<body>"
        f"{_cover_and_toc(pages, title=title, source_root=html_root)}"
        f"{''.join(sections)}"
        "</body>"
        "</html>"
    )


async def render_pdf(
    html: str,
    out: Path,
    *,
    html_root: Path,
    page_size: str = "A4",
    keep_html: bool = False,
) -> Path:
    """Render `html` to a PDF at `out`. Returns the PDF path."""
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError(
            "PDF export requires Playwright. Run `gimmethatdata setup` to install."
        ) from exc

    html_file = html_root / "_export.html"
    html_file.write_text(html, encoding="utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context()
            page = await ctx.new_page()
            file_url = "file:///" + str(html_file.resolve()).replace("\\", "/")
            await page.goto(file_url, wait_until="domcontentloaded")
            await page.wait_for_load_state("networkidle", timeout=15000)
            await page.pdf(
                path=str(out),
                format=page_size,
                print_background=True,
                margin={"top": "18mm", "right": "16mm", "bottom": "18mm", "left": "16mm"},
            )
        finally:
            await browser.close()

    if not keep_html:
        with contextlib.suppress(OSError):
            html_file.unlink()
    _log.info("pdf_written", path=str(out), pages=html.count("page-section"))
    return out


async def export_to_pdf(
    source_root: Path,
    *,
    out: Path,
    title: str | None = None,
    page_size: str = "A4",
    keep_html: bool = False,
) -> Path:
    """Discover pages under `source_root` and render them to a PDF at `out`."""
    pages = discover_pages(source_root)
    if not pages:
        raise FileNotFoundError(
            f"no `content.md` files found under {source_root}"
        )
    resolved_title = title or _default_title(source_root, pages)
    html = build_html(pages, title=resolved_title, html_root=source_root)
    return await render_pdf(
        html, out, html_root=source_root, page_size=page_size, keep_html=keep_html
    )


def _default_title(source_root: Path, pages: list[PageBundle]) -> str:
    domain = source_root.name
    if not pages:
        return f"gimmethatdata · {domain}"
    if len(pages) == 1:
        return pages[0].metadata.get("title") or f"gimmethatdata · {domain}"
    when = datetime.now().strftime("%Y-%m-%d")
    return f"gimmethatdata · {domain} · {when}"
