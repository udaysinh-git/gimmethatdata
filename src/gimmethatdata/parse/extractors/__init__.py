"""Built-in site-specific extractors."""

from __future__ import annotations

from gimmethatdata.parse.extractors.reddit import RedditExtractor
from gimmethatdata.parse.plugins import Extractor


def builtin_extractors() -> list[Extractor]:
    return [RedditExtractor()]
