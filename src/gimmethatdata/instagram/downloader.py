"""Download an Instagram profile into the project's standard output layout.

Each post / reel / highlight item lands in its own folder so the rest of the
tool (search, diff, export-pdf) treats it like any other scraped page.

Layout:

  <out_root>/instagram/<username>/
    profile.json                       # bio + counts (no media)
    posts/<shortcode>/
      content.md                       # caption + frontmatter
      metadata.json                    # full post metadata
      comments.json                    # comments (when allowed; login required)
      assets.json                      # list of media URLs + local paths
      assets/images/<sha>.jpg          # photo carousel members
    reels/<shortcode>/
      content.md, metadata.json,
      comments.json, assets.json       # reels store only the cover image
      assets/images/<sha>.jpg          # cover frame
    highlights/<title>/<id>/
      content.md, assets.json, assets/images/<sha>.jpg
    stories/<id>/
      content.md, assets.json, assets/images/<sha>.jpg

Backend: instagrapi (Instagram's mobile private API).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from gimmethatdata.instagram.client import InstagramClient
from gimmethatdata.logging_setup import get_logger

if TYPE_CHECKING:
    from instagrapi.types import Media, User

_log = get_logger(__name__)

_SLUG_RE = re.compile(r"[^a-zA-Z0-9_-]+")


def _slug(text: str, *, max_len: int = 40) -> str:
    slug = _SLUG_RE.sub("-", (text or "").strip()).strip("-")
    return slug[:max_len] or "untitled"


@dataclass
class DownloadOptions:
    fetch_posts: bool = True
    fetch_reels: bool = True
    fetch_highlights: bool = False
    fetch_stories: bool = False
    fetch_tagged: bool = False
    fetch_comments: bool = True
    fetch_likers: bool = False
    fetch_comment_replies: bool = False
    enrich_locations: bool = False
    download_images: bool = True
    limit: int | None = None
    comments_per_post: int = 100
    likers_per_post: int = 100
    since: datetime | None = None  # incremental: skip posts older than this
    resume: bool = True  # skip shortcodes already on disk
    ocr_images: bool = False


@dataclass
class DownloadReport:
    profile: dict[str, Any]
    posts: int = 0
    reels: int = 0
    highlights: int = 0
    stories: int = 0
    tagged: int = 0
    images_downloaded: int = 0
    comments_collected: int = 0
    likers_collected: int = 0
    skipped_existing: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "username": self.profile.get("username"),
            "posts": self.posts,
            "reels": self.reels,
            "highlights": self.highlights,
            "stories": self.stories,
            "tagged": self.tagged,
            "images_downloaded": self.images_downloaded,
            "comments_collected": self.comments_collected,
            "likers_collected": self.likers_collected,
            "skipped_existing": self.skipped_existing,
            "errors": self.errors,
        }


def download_profile(
    client: InstagramClient,
    username: str,
    *,
    out_root: Path,
    options: DownloadOptions | None = None,
    on_progress: Callable[[str, dict[str, Any]], None] | None = None,
) -> DownloadReport:
    """Download a public/accessible profile end-to-end, returning a report."""
    from instagrapi.exceptions import (
        ClientError,
        UserNotFound,
    )

    opts = options or DownloadOptions()
    target_root = out_root / "instagram" / username
    target_root.mkdir(parents=True, exist_ok=True)
    ig = client.client  # instagrapi.Client

    try:
        user = ig.user_info_by_username(username)
    except UserNotFound as exc:
        raise RuntimeError(f"profile not found: {username}") from exc
    except ClientError as exc:
        raise RuntimeError(
            f"profile lookup failed for @{username}: {exc}. "
            "If this persists, mint a fresh session via `ig-import-cookie`."
        ) from exc

    profile_dict = _serialize_user(user)
    (target_root / "profile.json").write_text(
        json.dumps(profile_dict, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    report = DownloadReport(profile=profile_dict)
    _emit(on_progress, "profile_loaded", {"username": username, "is_private": user.is_private})

    if user.is_private and client.logged_in_as is None:
        report.errors.append("profile is private and client is anonymous")
        return report
    if user.is_private and not _follows(ig, user):
        report.errors.append(
            f"profile is private and @{client.logged_in_as} doesn't follow @{username}"
        )
        return report

    if opts.fetch_posts or opts.fetch_reels:
        _walk_posts(
            ig, user, target_root,
            report=report, options=opts, on_progress=on_progress, client=client,
        )

    if opts.fetch_highlights:
        if client.logged_in_as is None:
            report.errors.append("highlights require login; skipping")
        else:
            _walk_highlights(ig, user, target_root, report=report, options=opts, on_progress=on_progress)

    if opts.fetch_stories:
        if client.logged_in_as is None:
            report.errors.append("stories require login; skipping")
        else:
            _walk_stories(ig, user, target_root, report=report, options=opts, on_progress=on_progress)

    if opts.fetch_tagged:
        _walk_tagged(
            ig, user, target_root,
            report=report, options=opts, on_progress=on_progress, client=client,
        )

    return report


def _follows(ig: Any, user: User) -> bool:
    """Return True if the logged-in account follows `user`. Best-effort."""
    try:
        return bool(getattr(user, "friendship_status", {}).following)  # type: ignore[union-attr]
    except (AttributeError, KeyError):
        return True  # default to optimistic — the data fetch will raise if not


def _walk_posts(
    ig: Any,
    user: User,
    target_root: Path,
    *,
    report: DownloadReport,
    options: DownloadOptions,
    on_progress: Callable[[str, dict[str, Any]], None] | None,
    client: InstagramClient,
) -> None:
    from instagrapi.exceptions import ClientError

    posts_dir = target_root / "posts"
    reels_dir = target_root / "reels"
    posts_dir.mkdir(parents=True, exist_ok=True)
    reels_dir.mkdir(parents=True, exist_ok=True)

    amount = options.limit or 0  # instagrapi: 0 = all
    try:
        medias = ig.user_medias(user.pk, amount=amount)
    except ClientError as exc:
        report.errors.append(f"user_medias: {exc}")
        return

    location_cache: dict[str, dict[str, Any]] = {}
    for index, media in enumerate(medias):
        is_reel = _is_reel(media)
        if is_reel and not options.fetch_reels:
            continue
        if not is_reel and not options.fetch_posts:
            continue
        if options.since is not None and media.taken_at and media.taken_at < options.since:
            # Posts come back newest-first; once we hit an older one, we're done.
            _log.info("ig_since_cutoff_hit", at=str(media.taken_at))
            break
        kind_dir = reels_dir if is_reel else posts_dir
        if options.resume and _already_archived(kind_dir / media.code):
            report.skipped_existing += 1
            _emit(
                on_progress,
                "post_skipped",
                {"shortcode": media.code, "reason": "already on disk"},
            )
            continue
        try:
            _save_media(
                ig, media, kind_dir,
                options=options, client=client, report=report,
                location_cache=location_cache,
            )
        except Exception as exc:
            report.errors.append(f"media {media.code}: {exc}")
            _log.warning("ig_media_failed", shortcode=media.code, error=str(exc))
            continue
        if is_reel:
            report.reels += 1
        else:
            report.posts += 1
        _emit(
            on_progress,
            "post_saved",
            {"shortcode": media.code, "kind": "reel" if is_reel else "post", "index": index},
        )


def _already_archived(post_dir: Path) -> bool:
    """A shortcode is considered done if it has content.md + a non-empty assets dir."""
    if not (post_dir / "content.md").exists():
        return False
    images_dir = post_dir / "assets" / "images"
    return images_dir.exists() and any(images_dir.iterdir())


def _save_media(
    ig: Any,
    media: Media,
    parent_dir: Path,
    *,
    options: DownloadOptions,
    client: InstagramClient,
    report: DownloadReport,
    location_cache: dict[str, dict[str, Any]] | None = None,
) -> None:
    from instagrapi.exceptions import ClientError

    post_dir = parent_dir / media.code
    post_dir.mkdir(parents=True, exist_ok=True)

    media_refs = _collect_media_refs(media)
    assets_list: list[dict[str, Any]] = []
    if options.download_images:
        for ref in media_refs:
            local = _download_media_file(ref["abs_url"], post_dir)
            if local is not None:
                ref["local_path"] = local
                ref["sha256"] = _file_sha(post_dir / local)
                report.images_downloaded += 1
            assets_list.append(ref)
    else:
        assets_list = media_refs

    metadata = _media_metadata(media)
    if options.enrich_locations and metadata.get("location"):
        metadata["location"] = _enrich_location(ig, metadata["location"], cache=location_cache)

    comments_payload: list[dict[str, Any]] = []
    if options.fetch_comments and client.logged_in_as is not None:
        try:
            raw_comments = ig.media_comments(media.id, amount=options.comments_per_post)
            comments_payload = [
                _serialize_comment(c, ig=ig, fetch_replies=options.fetch_comment_replies)
                for c in raw_comments
            ]
            report.comments_collected += len(comments_payload) + sum(
                len(c.get("replies") or []) for c in comments_payload
            )
        except ClientError as exc:
            report.errors.append(f"comments {media.code}: {exc}")

    likers_payload: list[dict[str, Any]] = []
    if options.fetch_likers and client.logged_in_as is not None:
        try:
            likers = ig.media_likers(media.id)
            likers_payload = [_serialize_user_short(u) for u in (likers or [])]
            report.likers_collected += len(likers_payload)
        except ClientError as exc:
            report.errors.append(f"likers {media.code}: {exc}")

    ocr_text = ""
    if options.ocr_images:
        ocr_text = _ocr_assets(post_dir, assets_list)

    content_md = _render_media_md(
        media, metadata=metadata, asset_count=len(assets_list), ocr_text=ocr_text
    )
    (post_dir / "content.md").write_text(content_md, encoding="utf-8")
    (post_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    (post_dir / "assets.json").write_text(
        json.dumps(assets_list, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    (post_dir / "comments.json").write_text(
        json.dumps(comments_payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    if likers_payload or options.fetch_likers:
        (post_dir / "likers.json").write_text(
            json.dumps(likers_payload, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )


def _walk_highlights(
    ig: Any,
    user: User,
    target_root: Path,
    *,
    report: DownloadReport,
    options: DownloadOptions,
    on_progress: Callable[[str, dict[str, Any]], None] | None,
) -> None:
    from instagrapi.exceptions import ClientError

    highlights_dir = target_root / "highlights"
    highlights_dir.mkdir(parents=True, exist_ok=True)
    try:
        highlights = ig.user_highlights(user.pk)
    except ClientError as exc:
        report.errors.append(f"highlights: {exc}")
        return
    for hl in highlights:
        title = _slug(getattr(hl, "title", "") or "untitled")
        hl_dir = highlights_dir / title
        hl_dir.mkdir(parents=True, exist_ok=True)
        items: list[dict[str, Any]] = []
        try:
            hl_full = ig.highlight_info(hl.pk)
            hl_items = hl_full.items
        except ClientError as exc:
            report.errors.append(f"highlight {hl.title}: {exc}")
            continue
        for item in hl_items:
            item_dir = hl_dir / str(item.pk)
            item_dir.mkdir(parents=True, exist_ok=True)
            url = _best_image_url(item)
            local = _download_media_file(url, item_dir) if options.download_images and url else None
            assets = [{
                "kind": "image",
                "abs_url": url,
                "local_path": local,
                "sha256": _file_sha(item_dir / local) if local else None,
            }]
            (item_dir / "assets.json").write_text(
                json.dumps(assets, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            (item_dir / "content.md").write_text(
                f"---\n"
                f'title: "highlight: {hl.title}"\n'
                f'url: "ig://highlight/{hl.pk}/{item.pk}"\n'
                f'fetched_at: "{datetime.now(UTC).isoformat()}"\n'
                f"---\n\n"
                f"# {hl.title}\n\n"
                f"Highlight item from {item.taken_at.isoformat() if item.taken_at else '?'}\n",
                encoding="utf-8",
            )
            items.append({"pk": item.pk, "taken_at": str(item.taken_at)})
            if local is not None:
                report.images_downloaded += 1
        (hl_dir / "highlight.json").write_text(
            json.dumps(
                {"pk": hl.pk, "title": hl.title, "items": items},
                indent=2,
                ensure_ascii=False,
                default=str,
            ),
            encoding="utf-8",
        )
        report.highlights += len(items)
        _emit(on_progress, "highlight_saved", {"title": hl.title, "items": len(items)})


def _walk_stories(
    ig: Any,
    user: User,
    target_root: Path,
    *,
    report: DownloadReport,
    options: DownloadOptions,
    on_progress: Callable[[str, dict[str, Any]], None] | None,
) -> None:
    from instagrapi.exceptions import ClientError

    stories_dir = target_root / "stories"
    stories_dir.mkdir(parents=True, exist_ok=True)
    try:
        stories = ig.user_stories(user.pk)
    except ClientError as exc:
        report.errors.append(f"stories: {exc}")
        return
    for story in stories:
        item_dir = stories_dir / str(story.pk)
        item_dir.mkdir(parents=True, exist_ok=True)
        url = _best_image_url(story)
        local = _download_media_file(url, item_dir) if options.download_images and url else None
        (item_dir / "assets.json").write_text(
            json.dumps(
                [{"kind": "image", "abs_url": url, "local_path": local}],
                indent=2,
                ensure_ascii=False,
                default=str,
            ),
            encoding="utf-8",
        )
        (item_dir / "content.md").write_text(
            f"---\n"
            f'title: "story"\n'
            f'url: "ig://story/{story.pk}"\n'
            f'fetched_at: "{datetime.now(UTC).isoformat()}"\n'
            f"---\n\n# Story {story.pk}\n\nFrom {story.taken_at.isoformat() if story.taken_at else '?'}\n",
            encoding="utf-8",
        )
        report.stories += 1
        if local is not None:
            report.images_downloaded += 1
        _emit(on_progress, "story_saved", {"pk": story.pk})


def _walk_tagged(
    ig: Any,
    user: User,
    target_root: Path,
    *,
    report: DownloadReport,
    options: DownloadOptions,
    on_progress: Callable[[str, dict[str, Any]], None] | None,
    client: InstagramClient,
) -> None:
    """Posts where this account was tagged by *others*."""
    from instagrapi.exceptions import ClientError

    tagged_dir = target_root / "tagged"
    tagged_dir.mkdir(parents=True, exist_ok=True)
    amount = options.limit or 0
    try:
        medias = ig.usertag_medias(user.pk, amount=amount)
    except ClientError as exc:
        report.errors.append(f"usertag_medias: {exc}")
        return
    location_cache: dict[str, dict[str, Any]] = {}
    for media in medias or []:
        if options.resume and _already_archived(tagged_dir / media.code):
            report.skipped_existing += 1
            continue
        try:
            _save_media(
                ig, media, tagged_dir,
                options=options, client=client, report=report,
                location_cache=location_cache,
            )
        except Exception as exc:
            report.errors.append(f"tagged {media.code}: {exc}")
            continue
        report.tagged += 1
        _emit(on_progress, "tagged_saved", {"shortcode": media.code})


def _enrich_location(
    ig: Any,
    location: dict[str, Any],
    *,
    cache: dict[str, dict[str, Any]] | None,
) -> dict[str, Any]:
    """Fetch the canonical location record (lat/lng/address) given a pk."""
    pk = str(location.get("pk") or "")
    if not pk:
        return location
    if cache is not None and pk in cache:
        return {**location, **cache[pk]}
    try:
        full = ig.location_info(int(pk))
    except Exception as exc:
        _log.debug("ig_location_enrich_failed", pk=pk, error=str(exc))
        return location
    enriched = {
        "pk": pk,
        "name": getattr(full, "name", location.get("name")),
        "lat": getattr(full, "lat", None),
        "lng": getattr(full, "lng", None),
        "address": getattr(full, "address", None),
        "city": getattr(full, "city", None),
    }
    if cache is not None:
        cache[pk] = enriched
    return enriched


def _serialize_user_short(user: object) -> dict[str, Any]:
    return {
        "pk": str(getattr(user, "pk", "")),
        "username": getattr(user, "username", "?"),
        "full_name": getattr(user, "full_name", None),
        "is_verified": getattr(user, "is_verified", False),
    }


def _ocr_assets(post_dir: Path, assets_list: list[dict[str, Any]]) -> str:
    """Run OCR over every downloaded image, return aggregated text."""
    try:
        from gimmethatdata.parse.ocr import _ocr_image_bytes
    except ImportError:
        return ""
    chunks: list[str] = []
    for asset in assets_list:
        local = asset.get("local_path")
        if not local:
            continue
        path = post_dir / local
        if not path.exists():
            continue
        try:
            body = path.read_bytes()
        except OSError:
            continue
        text = _ocr_image_bytes(body)
        if text and len(text.strip()) >= 8:
            chunks.append(text.strip())
    return "\n\n---\n\n".join(chunks)


def _is_reel(media: Media) -> bool:
    """media_type 2 + product_type 'clips' or 'feed_video' → reel/video."""
    product_type = getattr(media, "product_type", "") or ""
    return getattr(media, "media_type", 0) == 2 and product_type in {"clips", "feed_video", "igtv"}


def _collect_media_refs(media: Media) -> list[dict[str, Any]]:
    """Image URLs per media. Carousels expand; videos return only the cover frame."""
    refs: list[dict[str, Any]] = []
    media_type = getattr(media, "media_type", 0)
    resources = getattr(media, "resources", None) or []
    if resources:
        for resource in resources:
            if getattr(resource, "media_type", 0) == 2:
                # Video slide in a carousel — keep the cover only.
                url = _safe_url(getattr(resource, "thumbnail_url", None))
                if url:
                    refs.append({"kind": "image", "abs_url": url, "is_video_cover": True})
                continue
            url = _safe_url(getattr(resource, "thumbnail_url", None))
            if url:
                refs.append({"kind": "image", "abs_url": url})
        return refs
    if media_type == 2:
        url = _safe_url(getattr(media, "thumbnail_url", None))
        if url:
            refs.append({"kind": "image", "abs_url": url, "is_video_cover": True})
        return refs
    url = _safe_url(getattr(media, "thumbnail_url", None))
    if url:
        refs.append({"kind": "image", "abs_url": url})
    return refs


def _media_metadata(media: Media) -> dict[str, Any]:
    location = getattr(media, "location", None)
    caption = (getattr(media, "caption_text", "") or "").strip()
    return {
        "shortcode": media.code,
        "pk": str(media.pk),
        "id": media.id,
        "url": f"https://www.instagram.com/p/{media.code}/",
        "owner_username": getattr(media.user, "username", None),
        "media_type": media.media_type,
        "product_type": getattr(media, "product_type", ""),
        "is_video": media.media_type == 2,
        "taken_at": media.taken_at.isoformat() if media.taken_at else None,
        "caption": caption,
        "likes": getattr(media, "like_count", 0),
        "comments_count": getattr(media, "comment_count", 0),
        "video_view_count": getattr(media, "view_count", None) or getattr(media, "play_count", None),
        "play_count": getattr(media, "play_count", None),
        "share_count": getattr(media, "share_count", None),
        "save_count": getattr(media, "save_count", None),
        "has_audio": getattr(media, "has_audio", None),
        "audio_info": _audio_info(media),
        "location": _location_dict(location),
        "tagged_users": _tagged_users(media),
        "hashtags": sorted({h.lower() for h in re.findall(r"(?<![\w])#([A-Za-z0-9_]+)", caption)}),
        "mentions": sorted({m.lower() for m in re.findall(r"(?<![\w])@([A-Za-z0-9._]+)", caption)}),
    }


def _audio_info(media: Media) -> dict[str, Any] | None:
    """Pull the reel/clips audio metadata if present."""
    clips_meta = getattr(media, "clips_metadata", None)
    if not clips_meta:
        return None
    music_info = getattr(clips_meta, "music_info", None) or getattr(
        clips_meta, "original_sound_info", None
    )
    if not music_info:
        return None
    asset = getattr(music_info, "music_asset_info", None) or music_info
    return {
        "title": getattr(asset, "title", None) or getattr(music_info, "title", None),
        "artist": (
            getattr(asset, "display_artist", None)
            or getattr(asset, "ig_artist", None)
            or getattr(asset, "artist", None)
        ),
        "audio_id": str(
            getattr(asset, "id", None)
            or getattr(asset, "audio_id", None)
            or getattr(music_info, "audio_id", "")
        ),
        "is_original": bool(getattr(music_info, "original_sound_info", None)),
        "duration_ms": getattr(asset, "duration_in_ms", None),
    }


def _location_dict(location: object) -> dict[str, Any] | None:
    if not location:
        return None
    return {
        "pk": str(getattr(location, "pk", "")),
        "name": getattr(location, "name", None),
        "lat": getattr(location, "lat", None),
        "lng": getattr(location, "lng", None),
        "address": getattr(location, "address", None),
        "city": getattr(location, "city", None),
    }


def _tagged_users(media: Media) -> list[dict[str, Any]]:
    tags = getattr(media, "usertags", None) or []
    out: list[dict[str, Any]] = []
    for tag in tags:
        user = getattr(tag, "user", None) or tag
        username = getattr(user, "username", None)
        if not username:
            continue
        out.append(
            {
                "username": username,
                "full_name": getattr(user, "full_name", None),
                "x": getattr(tag, "x", None),
                "y": getattr(tag, "y", None),
            }
        )
    return out


def _serialize_comment(
    comment: object,
    *,
    ig: Any = None,
    fetch_replies: bool = False,
) -> dict[str, Any]:
    replies: list[dict[str, Any]] = []
    child_count = int(getattr(comment, "child_comment_count", 0) or 0)
    if fetch_replies and child_count > 0 and ig is not None:
        replies = _fetch_comment_replies(ig, comment)
    return {
        "pk": str(getattr(comment, "pk", "")),
        "owner": getattr(getattr(comment, "user", None), "username", "?"),
        "text": getattr(comment, "text", ""),
        "likes": getattr(comment, "like_count", 0),
        "created_at": (
            getattr(comment, "created_at_utc", None)
            or getattr(comment, "created_at", None)
        ),
        "child_comment_count": child_count,
        "replies": replies,
    }


def _fetch_comment_replies(ig: Any, parent: object) -> list[dict[str, Any]]:
    """Best-effort: try instagrapi's reply endpoint, fall back to empty."""
    parent_pk = getattr(parent, "pk", None)
    media_id = getattr(parent, "media_id", None) or getattr(parent, "media", None)
    if parent_pk is None or media_id is None:
        return []
    fetcher = getattr(ig, "media_comment_replies", None) or getattr(
        ig, "comment_replies", None
    )
    if fetcher is None:
        return []
    try:
        raw = fetcher(media_id, parent_pk) if media_id is not None else fetcher(parent_pk)
    except Exception as exc:
        _log.debug("ig_replies_failed", parent_pk=str(parent_pk), error=str(exc))
        return []
    return [
        {
            "pk": str(getattr(r, "pk", "")),
            "owner": getattr(getattr(r, "user", None), "username", "?"),
            "text": getattr(r, "text", ""),
            "likes": getattr(r, "like_count", 0),
            "created_at": getattr(r, "created_at_utc", None),
        }
        for r in (raw or [])
    ]


def _render_media_md(
    media: Media,
    *,
    metadata: dict[str, Any],
    asset_count: int,
    ocr_text: str = "",
) -> str:
    caption = (getattr(media, "caption_text", "") or "").strip()
    title = caption.splitlines()[0][:80] if caption else media.code
    owner = getattr(media.user, "username", "?")
    taken = media.taken_at.isoformat() if media.taken_at else "?"
    likes = metadata.get("likes", 0)
    comments = metadata.get("comments_count", 0)
    plays = metadata.get("play_count") or metadata.get("video_view_count")
    shares = metadata.get("share_count")
    saves = metadata.get("save_count")

    lines = [
        "---",
        f'url: "https://www.instagram.com/p/{media.code}/"',
        f'final_url: "https://www.instagram.com/p/{media.code}/"',
        f'title: "{_yaml_escape(title)}"',
        f'fetched_at: "{datetime.now(UTC).isoformat()}"',
        "status_code: 200",
        'tier: "instagram"',
        f"likes: {likes}",
        f"comments_count: {comments}",
        f"is_video: {str(media.media_type == 2).lower()}",
        f"images: {asset_count}",
    ]
    if plays:
        lines.append(f"plays: {plays}")
    if shares:
        lines.append(f"shares: {shares}")
    if saves:
        lines.append(f"saves: {saves}")
    audio = metadata.get("audio_info")
    if audio and audio.get("title"):
        lines.append(f'audio_title: "{_yaml_escape(audio["title"])}"')
        if audio.get("artist"):
            lines.append(f'audio_artist: "{_yaml_escape(audio["artist"])}"')
    lines.extend(
        [
            "---",
            "",
            f"# {title}",
            "",
            f"_posted by **@{owner}** on {taken}_",
            "",
        ]
    )

    badges = [f"❤ {likes}", f"💬 {comments}"]
    if plays:
        badges.append(f"▶ {plays:,}")
    if shares:
        badges.append(f"↗ {shares}")
    if saves:
        badges.append(f"🔖 {saves}")
    lines.append("  ·  ".join(badges))
    lines.append("")

    if caption:
        lines.append(caption)
        lines.append("")
    if metadata.get("hashtags"):
        lines.append("**Hashtags:** " + " ".join(f"#{h}" for h in metadata["hashtags"]))
        lines.append("")
    if metadata.get("mentions"):
        lines.append("**Mentions:** " + " ".join(f"@{m}" for m in metadata["mentions"]))
        lines.append("")
    if metadata.get("tagged_users"):
        names = " ".join(f"@{t['username']}" for t in metadata["tagged_users"])
        lines.append(f"**Tagged in photo:** {names}")
        lines.append("")
    location = metadata.get("location")
    if location and location.get("name"):
        loc_line = f"**Location:** {location['name']}"
        if location.get("lat") and location.get("lng"):
            loc_line += f" ([{location['lat']:.4f}, {location['lng']:.4f}](https://www.google.com/maps?q={location['lat']},{location['lng']}))"
        lines.append(loc_line)
        lines.append("")
    if audio and audio.get("title"):
        audio_line = f"**Audio:** {audio['title']}"
        if audio.get("artist"):
            audio_line += f" — _{audio['artist']}_"
        if audio.get("is_original"):
            audio_line += " · _original sound_"
        lines.append(audio_line)
        lines.append("")
    if ocr_text:
        lines.append("## OCR")
        lines.append("")
        lines.append(ocr_text)
        lines.append("")
    return "\n".join(lines) + "\n"


def _serialize_user(user: User) -> dict[str, Any]:
    return {
        "username": user.username,
        "pk": str(user.pk),
        "full_name": user.full_name,
        "biography": getattr(user, "biography", ""),
        "followers": getattr(user, "follower_count", 0),
        "followees": getattr(user, "following_count", 0),
        "media_count": getattr(user, "media_count", 0),
        "is_private": user.is_private,
        "is_verified": getattr(user, "is_verified", False),
        "external_url": getattr(user, "external_url", None),
        "profile_pic_url": str(getattr(user, "profile_pic_url", "") or ""),
    }


def _yaml_escape(text: str) -> str:
    return text.replace('"', '\\"')


def _safe_url(url: object) -> str | None:
    if url is None:
        return None
    s = str(url)
    return s or None


def _best_image_url(item: object) -> str | None:
    """Pick the best still-image URL from a story / highlight item."""
    return _safe_url(getattr(item, "thumbnail_url", None) or getattr(item, "image_versions2", None))


def _download_media_file(url: str | None, page_dir: Path) -> str | None:
    if not url:
        return None
    images_dir = page_dir / "assets" / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    try:
        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
            body = response.content
    except httpx.HTTPError as exc:
        _log.warning("ig_media_download_failed", url=url, error=str(exc))
        return None
    sha = hashlib.sha256(body).hexdigest()
    ext = _guess_ext(url, response.headers.get("content-type"))
    target = images_dir / f"{sha}{ext}"
    if not target.exists():
        target.write_bytes(body)
    return str(target.relative_to(page_dir)).replace("\\", "/")


def _guess_ext(url: str, content_type: str | None) -> str:
    path = url.split("?", 1)[0]
    dot = path.rfind(".")
    if dot >= 0:
        ext = path[dot:].lower()
        if 1 < len(ext) <= 6 and ext.isascii():
            return ext
    if content_type and "/" in content_type:
        return "." + content_type.split("/")[1].split(";")[0].strip()
    return ".bin"


def _file_sha(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _emit(
    callback: Callable[[str, dict[str, Any]], None] | None,
    event: str,
    payload: dict[str, Any],
) -> None:
    if callback is None:
        return
    try:
        callback(event, payload)
    except Exception as exc:
        _log.debug("progress_callback_failed", error=str(exc))


async def download_profile_async(
    client: InstagramClient,
    username: str,
    *,
    out_root: Path,
    options: DownloadOptions | None = None,
    on_progress: Callable[[str, dict[str, Any]], None] | None = None,
) -> DownloadReport:
    """Run the (blocking) instagrapi download in a worker thread."""
    return await asyncio.to_thread(
        download_profile,
        client,
        username,
        out_root=out_root,
        options=options,
        on_progress=on_progress,
    )
