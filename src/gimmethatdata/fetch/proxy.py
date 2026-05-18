"""Proxy pool with rotation strategies."""

from __future__ import annotations

import itertools
import random
from collections.abc import Iterator
from enum import StrEnum
from pathlib import Path


class ProxyStrategy(StrEnum):
    ROUND_ROBIN = "round-robin"
    PER_FAILURE = "per-failure"
    STICKY = "sticky-per-domain"
    RANDOM = "random"


class ProxyPool:
    """Holds a list of proxy URLs and hands them out per strategy."""

    def __init__(
        self,
        proxies: list[str],
        strategy: ProxyStrategy = ProxyStrategy.ROUND_ROBIN,
    ) -> None:
        self._proxies = [p for p in (p.strip() for p in proxies) if p]
        self._strategy = strategy
        self._cycle: Iterator[str] | None = (
            itertools.cycle(self._proxies) if self._proxies else None
        )
        self._sticky: dict[str, str] = {}
        self._current: str | None = next(self._cycle) if self._cycle else None

    @classmethod
    def from_file(cls, path: Path, strategy: ProxyStrategy = ProxyStrategy.ROUND_ROBIN) -> ProxyPool:
        lines = [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        return cls(lines, strategy=strategy)

    @classmethod
    def from_single(cls, proxy: str | None) -> ProxyPool:
        return cls([proxy] if proxy else [])

    def __len__(self) -> int:
        return len(self._proxies)

    def __bool__(self) -> bool:
        return bool(self._proxies)

    def pick(self, *, domain: str | None = None) -> str | None:
        if not self._proxies or self._cycle is None:
            return None
        if self._strategy is ProxyStrategy.STICKY and domain is not None:
            picked = self._sticky.get(domain)
            if picked is None:
                picked = next(self._cycle)
                self._sticky[domain] = picked
            return picked
        if self._strategy is ProxyStrategy.PER_FAILURE:
            return self._current
        if self._strategy is ProxyStrategy.RANDOM:
            return random.choice(self._proxies)
        return next(self._cycle)

    def report_failure(self) -> None:
        """Advance the pool on PER_FAILURE strategy."""
        if self._cycle is None:
            return
        self._current = next(self._cycle)
