"""Pydantic data models shared across the pipeline."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


def utcnow() -> datetime:
    return datetime.now(UTC)


class AssetKind(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    EMBED = "embed"
    OTHER = "other"


class FetchTier(StrEnum):
    HTTPX = "httpx"
    CURL_CFFI = "curl_cffi"
    PLAYWRIGHT = "playwright"
    FLARESOLVERR = "flaresolverr"


class FetchAttempt(BaseModel):
    tier: FetchTier
    status_code: int | None = None
    error: str | None = None
    elapsed_ms: int


class FetchResult(BaseModel):
    """Result of a successful fetch from any tier."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    url: str
    final_url: str
    status_code: int
    headers: dict[str, str]
    body: bytes
    encoding: str | None = None
    tier: FetchTier
    elapsed_ms: int
    attempts: list[FetchAttempt] = Field(default_factory=list)
    fetched_at: datetime = Field(default_factory=utcnow)

    @property
    def text(self) -> str:
        return self.body.decode(self.encoding or "utf-8", errors="replace")


class AssetRef(BaseModel):
    """A single asset referenced from a page."""

    kind: AssetKind
    url: str
    abs_url: str
    alt: str | None = None
    title: str | None = None
    width: int | None = None
    height: int | None = None
    mime: str | None = None
    sha256: str | None = None
    local_path: str | None = None
    bytes_: int | None = Field(default=None, alias="bytes")


class LinkRef(BaseModel):
    """An <a href> link discovered on a page."""

    url: str
    abs_url: str
    anchor: str
    rel: list[str] = Field(default_factory=list)
    internal: bool


class PageMetadata(BaseModel):
    """Metadata block written to metadata.json."""

    url: str
    final_url: str
    title: str | None = None
    description: str | None = None
    lang: str | None = None
    canonical: str | None = None
    headings: dict[str, list[str]] = Field(default_factory=dict)
    meta: dict[str, str] = Field(default_factory=dict)
    og: dict[str, str] = Field(default_factory=dict)
    twitter: dict[str, str] = Field(default_factory=dict)
    jsonld: list[dict[str, Any]] = Field(default_factory=list)
    http_headers: dict[str, str] = Field(default_factory=dict)
    status_code: int
    tier: FetchTier
    elapsed_ms: int
    fetched_at: datetime = Field(default_factory=utcnow)


class PageResult(BaseModel):
    """End-of-pipeline result for one page."""

    url: HttpUrl | str
    output_dir: Path
    metadata: PageMetadata
    content_md: str
    assets: list[AssetRef]
    links: list[LinkRef]
    raw_html_path: Path | None = None
