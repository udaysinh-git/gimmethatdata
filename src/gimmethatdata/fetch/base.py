"""Fetcher protocol shared by every tier."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from gimmethatdata.core.models import FetchResult


@runtime_checkable
class Fetcher(Protocol):
    """Async fetcher returning a uniform FetchResult."""

    async def fetch(self, url: str) -> FetchResult: ...

    async def aclose(self) -> None: ...
