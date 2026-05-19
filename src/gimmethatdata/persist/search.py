"""SQLite FTS5 full-text index across every scraped `content.md`.

Index lives at `<out_root>/_search.sqlite`. Rebuilt with `index_all()` on
demand. Searches are simple FTS5 MATCH queries with snippet highlighting.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class SearchHit:
    url: str
    title: str
    output_dir: str
    snippet: str
    rank: float


_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS pages USING fts5(
    url UNINDEXED,
    title,
    output_dir UNINDEXED,
    content,
    tokenize = 'porter unicode61'
);
"""


class SearchIndex:
    """FTS5 index manager."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> SearchIndex:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def clear(self) -> None:
        self._conn.execute("DELETE FROM pages")
        self._conn.commit()

    def index_pages(self, root: Path) -> int:
        """Walk `root`, add every `content.md` to the index. Returns count added."""
        count = 0
        rows: list[tuple[str, str, str, str]] = []
        for md_path in root.rglob("content.md"):
            page_dir = md_path.parent
            url, title = _read_url_title(page_dir)
            body = _strip_frontmatter(md_path.read_text(encoding="utf-8"))
            rows.append((url, title, str(page_dir), body))
            count += 1
            if len(rows) >= 200:
                self._insert(rows)
                rows.clear()
        if rows:
            self._insert(rows)
        return count

    def _insert(self, rows: list[tuple[str, str, str, str]]) -> None:
        self._conn.executemany(
            "INSERT INTO pages (url, title, output_dir, content) VALUES (?, ?, ?, ?)",
            rows,
        )
        self._conn.commit()

    def search(self, query: str, *, limit: int = 25) -> list[SearchHit]:
        """FTS5 MATCH with snippet preview around the first hit."""
        clean = _sanitize_fts(query)
        if not clean:
            return []
        cursor = self._conn.execute(
            """
            SELECT url, title, output_dir,
                   snippet(pages, 3, '[match]', '[/match]', '…', 12) AS snippet,
                   rank
            FROM pages
            WHERE pages MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (clean, limit),
        )
        hits: list[SearchHit] = []
        for url, title, out_dir, snippet, rank in cursor:
            hits.append(
                SearchHit(
                    url=url or "",
                    title=title or "(untitled)",
                    output_dir=out_dir or "",
                    snippet=snippet or "",
                    rank=float(rank),
                )
            )
        return hits


def _read_url_title(page_dir: Path) -> tuple[str, str]:
    import json

    meta_path = page_dir / "metadata.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            url = str(meta.get("final_url") or meta.get("url") or "")
            title = str(meta.get("title") or page_dir.name)
            return url, title
        except (OSError, json.JSONDecodeError):
            pass
    return str(page_dir), page_dir.name


def _strip_frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---", 4)
    if end < 0:
        return text
    return text[end + 4 :].lstrip("\n")


def _sanitize_fts(query: str) -> str:
    """Wrap raw user input so FTS5 doesn't choke on bare punctuation."""
    cleaned = query.strip()
    if not cleaned:
        return ""
    # Easiest safe form: quote the whole query so it's a phrase or set of terms.
    # Multi-word stays multi-word; punctuation becomes literal.
    safe = cleaned.replace('"', "")
    return f'"{safe}"'


def index_all(out_root: Path) -> int:
    """Convenience: drop + rebuild the index across the entire out_root."""
    db_path = out_root / "_search.sqlite"
    with SearchIndex(db_path) as idx:
        idx.clear()
        return idx.index_pages(out_root)
