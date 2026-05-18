"""Pluggable site-specific extractors discovered via `entry_points`.

A plugin is any callable installed under the `gimmethatdata.extractors` group
that implements the `Extractor` protocol.

Example in a plugin package's `pyproject.toml`:

    [project.entry-points."gimmethatdata.extractors"]
    reddit = "my_pkg.reddit:extractor"
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Protocol, runtime_checkable

from gimmethatdata.logging_setup import get_logger

_log = get_logger(__name__)

ENTRY_POINT_GROUP = "gimmethatdata.extractors"


@dataclass
class ExtractedDocument:
    """What a plugin returns after parsing a page."""

    main_html: str
    title: str | None = None
    extra_meta: dict[str, str] | None = None


@runtime_checkable
class Extractor(Protocol):
    """A site-specific extractor."""

    name: str

    def matches(self, url: str) -> bool: ...

    def extract(self, html: str, *, url: str) -> ExtractedDocument | None: ...


def _builtin_extractors() -> list[Extractor]:
    return []


def discover_extractors() -> list[Extractor]:
    """Return all extractors registered under the entry-point group."""
    discovered: list[Extractor] = list(_builtin_extractors())
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        try:
            obj = ep.load()
            candidate = obj() if callable(obj) and not isinstance(obj, type) else obj
            if isinstance(candidate, Extractor):
                discovered.append(candidate)
            else:
                _log.warning(
                    "extractor_invalid_shape",
                    name=ep.name,
                    type=type(candidate).__name__,
                )
        except Exception as exc:
            _log.warning("extractor_load_failed", name=ep.name, error=str(exc))
    return discovered


def select_extractor(
    extractors: list[Extractor], url: str
) -> Extractor | None:
    """Return the first extractor matching `url`, or None."""
    for extractor in extractors:
        try:
            if extractor.matches(url):
                return extractor
        except Exception as exc:
            _log.warning(
                "extractor_match_error",
                name=getattr(extractor, "name", "?"),
                error=str(exc),
            )
    return None
