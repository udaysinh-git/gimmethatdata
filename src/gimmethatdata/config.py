"""Configuration for gimmethatdata.

Resolution order (later overrides earlier):
  1. Built-in defaults below.
  2. `~/.config/gimmethatdata/config.toml` (user-global, optional).
  3. `./gimmethatdata.toml` (project-local, optional).
  4. Environment variables prefixed `GIMMETHATDATA_`.
  5. CLI flags (applied at the call site, not here).
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class FetchSettings(BaseSettings):
    """HTTP / browser fetch defaults."""

    timeout_seconds: float = 30.0
    max_retries: int = 3
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    per_domain_rps: float = 2.0
    follow_redirects: bool = True
    verify_tls: bool = True


class CrawlSettings(BaseSettings):
    """Defaults for site-wide crawls."""

    max_depth: int = 2
    max_pages: int = 100
    same_domain_only: bool = True
    respect_robots: bool = True


class MediaSettings(BaseSettings):
    """Defaults for asset download pipeline."""

    download_images: bool = False
    download_videos: bool = False
    max_asset_mb: int = 50
    asset_types: tuple[str, ...] = ("image",)


class Settings(BaseSettings):
    """Root settings object — composed of subsections."""

    model_config = SettingsConfigDict(
        env_prefix="GIMMETHATDATA_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    out_root: Path = Field(default=Path("out"))
    concurrency: int = 8
    log_level: str = "INFO"

    fetch: FetchSettings = Field(default_factory=FetchSettings)
    crawl: CrawlSettings = Field(default_factory=CrawlSettings)
    media: MediaSettings = Field(default_factory=MediaSettings)


_USER_CONFIG = Path.home() / ".config" / "gimmethatdata" / "config.toml"
_PROJECT_CONFIG = Path.cwd() / "gimmethatdata.toml"


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def load_settings() -> Settings:
    """Load and merge settings from all sources."""
    merged: dict[str, Any] = {}
    for path in (_USER_CONFIG, _PROJECT_CONFIG):
        for k, v in _read_toml(path).items():
            merged[k] = v
    return Settings(**merged)
