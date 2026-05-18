"""User-Agent + Accept-* header rotation pool."""

from __future__ import annotations

import itertools
from collections.abc import Iterator

_DESKTOP_UAS: tuple[str, ...] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
)

_ACCEPT_LANGS: tuple[str, ...] = (
    "en-US,en;q=0.9",
    "en-GB,en;q=0.9",
    "en;q=0.9",
)


class HeaderPool:
    """Round-robin User-Agent + Accept-Language."""

    def __init__(
        self,
        user_agents: tuple[str, ...] = _DESKTOP_UAS,
        accept_langs: tuple[str, ...] = _ACCEPT_LANGS,
    ) -> None:
        self._uas: Iterator[str] = itertools.cycle(user_agents)
        self._langs: Iterator[str] = itertools.cycle(accept_langs)

    def next_headers(self) -> dict[str, str]:
        ua = next(self._uas)
        lang = next(self._langs)
        return {
            "User-Agent": ua,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": lang,
            "Accept-Encoding": "gzip, deflate, br",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
        }
