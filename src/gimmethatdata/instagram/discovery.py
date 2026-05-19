"""Hashtag- / location- / music-driven archives.

Reuses the per-media saver from `downloader._save_media` so output lands in
the same shape — every saved item gets `content.md`, `metadata.json`,
`assets.json`, optional `comments.json` and `assets/images/...`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gimmethatdata.instagram.client import InstagramClient
from gimmethatdata.instagram.downloader import (
    DownloadOptions,
    DownloadReport,
    _already_archived,
    _emit,
    _save_media,
)
from gimmethatdata.logging_setup import get_logger

_log = get_logger(__name__)


@dataclass
class DiscoveryReport:
    kind: str  # "hashtag" | "location" | "music"
    key: str
    target_dir: Path
    saved: int = 0
    skipped_existing: int = 0
    images_downloaded: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "key": self.key,
            "target_dir": str(self.target_dir),
            "saved": self.saved,
            "skipped_existing": self.skipped_existing,
            "images_downloaded": self.images_downloaded,
            "errors": self.errors,
        }


def discover_hashtag(
    client: InstagramClient,
    tag: str,
    *,
    out_root: Path,
    sort: str = "top",  # "top" | "recent"
    amount: int = 50,
    options: DownloadOptions | None = None,
    on_progress: Callable[[str, dict[str, Any]], None] | None = None,
) -> DiscoveryReport:
    """Archive top/recent posts for a hashtag."""
    from instagrapi.exceptions import ClientError

    opts = options or DownloadOptions(fetch_comments=False)
    target = out_root / "instagram" / "hashtags" / tag.lower()
    target.mkdir(parents=True, exist_ok=True)
    report = DiscoveryReport(kind="hashtag", key=tag.lower(), target_dir=target)
    ig = client.client

    fetch = (
        ig.hashtag_medias_top_v1 if sort == "top" else ig.hashtag_medias_recent_v1
    )
    try:
        medias = fetch(tag, amount=amount)
    except ClientError as exc:
        report.errors.append(f"hashtag fetch: {exc}")
        return report

    _save_each(medias, target, report=report, options=opts, client=client, on_progress=on_progress)
    return report


def discover_location(
    client: InstagramClient,
    location_pk: int,
    *,
    out_root: Path,
    sort: str = "top",
    amount: int = 50,
    options: DownloadOptions | None = None,
    on_progress: Callable[[str, dict[str, Any]], None] | None = None,
) -> DiscoveryReport:
    """Archive top/recent posts for an Instagram location."""
    from instagrapi.exceptions import ClientError

    opts = options or DownloadOptions(fetch_comments=False)
    target = out_root / "instagram" / "locations" / str(location_pk)
    target.mkdir(parents=True, exist_ok=True)
    report = DiscoveryReport(kind="location", key=str(location_pk), target_dir=target)
    ig = client.client

    fetch = (
        ig.location_medias_top_v1 if sort == "top" else ig.location_medias_recent_v1
    )
    try:
        medias = fetch(location_pk, amount=amount)
    except ClientError as exc:
        report.errors.append(f"location fetch: {exc}")
        return report

    _save_each(medias, target, report=report, options=opts, client=client, on_progress=on_progress)
    return report


def discover_music(
    client: InstagramClient,
    track_id: int,
    *,
    out_root: Path,
    amount: int = 50,
    options: DownloadOptions | None = None,
    on_progress: Callable[[str, dict[str, Any]], None] | None = None,
) -> DiscoveryReport:
    """Archive posts using a given music/audio track."""
    from instagrapi.exceptions import ClientError

    opts = options or DownloadOptions(fetch_comments=False)
    target = out_root / "instagram" / "music" / str(track_id)
    target.mkdir(parents=True, exist_ok=True)
    report = DiscoveryReport(kind="music", key=str(track_id), target_dir=target)
    ig = client.client

    fetcher = getattr(ig, "track_medias_v1", None) or getattr(ig, "track_medias", None)
    if fetcher is None:
        report.errors.append("instagrapi build lacks track_medias_v1 endpoint")
        return report
    try:
        medias = fetcher(track_id, amount=amount)
    except ClientError as exc:
        report.errors.append(f"music fetch: {exc}")
        return report

    _save_each(medias, target, report=report, options=opts, client=client, on_progress=on_progress)
    return report


def _save_each(
    medias: list[Any],
    target_dir: Path,
    *,
    report: DiscoveryReport,
    options: DownloadOptions,
    client: InstagramClient,
    on_progress: Callable[[str, dict[str, Any]], None] | None,
) -> None:
    """Adapt downloader's _save_media (which counts into DownloadReport) into our shape."""
    download_report = DownloadReport(profile={"username": target_dir.name})
    location_cache: dict[str, dict[str, Any]] = {}
    for media in medias or []:
        if options.resume and _already_archived(target_dir / media.code):
            report.skipped_existing += 1
            continue
        try:
            _save_media(
                client.client, media, target_dir,
                options=options, client=client, report=download_report,
                location_cache=location_cache,
            )
        except Exception as exc:
            report.errors.append(f"{media.code}: {exc}")
            _log.warning("ig_discovery_save_failed", code=media.code, error=str(exc))
            continue
        report.saved += 1
        _emit(on_progress, "discovery_saved", {"shortcode": media.code, "kind": report.kind})
    report.images_downloaded = download_report.images_downloaded
    if download_report.errors:
        report.errors.extend(download_report.errors)
