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
from typing import Any

import httpx
import instaloader

from gimmethatdata.instagram.client import InstagramClient
from gimmethatdata.logging_setup import get_logger

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
    fetch_comments: bool = True
    download_images: bool = True
    limit: int | None = None
    concurrency: int = 4


@dataclass
class DownloadReport:
    profile: dict[str, Any]
    posts: int = 0
    reels: int = 0
    highlights: int = 0
    stories: int = 0
    images_downloaded: int = 0
    comments_collected: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "username": self.profile.get("username"),
            "posts": self.posts,
            "reels": self.reels,
            "highlights": self.highlights,
            "stories": self.stories,
            "images_downloaded": self.images_downloaded,
            "comments_collected": self.comments_collected,
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
    opts = options or DownloadOptions()
    target_root = out_root / "instagram" / username
    target_root.mkdir(parents=True, exist_ok=True)

    try:
        profile = instaloader.Profile.from_username(client.loader.context, username)
    except instaloader.exceptions.ProfileNotExistsException as exc:
        raise RuntimeError(f"profile not found: {username}") from exc

    profile_dict = _serialize_profile(profile)
    (target_root / "profile.json").write_text(
        json.dumps(profile_dict, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    report = DownloadReport(profile=profile_dict)
    _emit(on_progress, "profile_loaded", {"username": username, "is_private": profile.is_private})

    if profile.is_private and client.logged_in_as is None:
        report.errors.append("profile is private and client is anonymous")
        return report

    if opts.fetch_posts or opts.fetch_reels:
        count = _walk_posts(
            client, profile, target_root, report=report, options=opts, on_progress=on_progress,
        )
        _emit(on_progress, "posts_done", {"count": count})

    if opts.fetch_highlights:
        if client.logged_in_as is None:
            report.errors.append("highlights require login; skipping")
        else:
            _walk_highlights(
                client, profile, target_root, report=report, options=opts, on_progress=on_progress,
            )

    if opts.fetch_stories:
        if client.logged_in_as is None:
            report.errors.append("stories require login; skipping")
        else:
            _walk_stories(
                client, profile, target_root, report=report, options=opts, on_progress=on_progress,
            )

    return report


def _walk_posts(
    client: InstagramClient,
    profile: instaloader.Profile,
    target_root: Path,
    *,
    report: DownloadReport,
    options: DownloadOptions,
    on_progress: Callable[[str, dict[str, Any]], None] | None,
) -> int:
    posts_dir = target_root / "posts"
    reels_dir = target_root / "reels"
    posts_dir.mkdir(parents=True, exist_ok=True)
    reels_dir.mkdir(parents=True, exist_ok=True)

    processed = 0
    for index, post in enumerate(profile.get_posts()):
        if options.limit is not None and processed >= options.limit:
            break
        is_reel = bool(getattr(post, "is_video", False)) and bool(
            getattr(post, "typename", "") in {"GraphVideo"}
        )
        kind_dir = reels_dir if is_reel else posts_dir
        if is_reel and not options.fetch_reels:
            continue
        if not is_reel and not options.fetch_posts:
            continue
        try:
            _save_post(post, kind_dir, options=options, client=client, report=report)
        except Exception as exc:
            report.errors.append(f"post {post.shortcode}: {exc}")
            _log.warning("ig_post_failed", shortcode=post.shortcode, error=str(exc))
            continue
        processed += 1
        if is_reel:
            report.reels += 1
        else:
            report.posts += 1
        _emit(
            on_progress,
            "post_saved",
            {"shortcode": post.shortcode, "kind": "reel" if is_reel else "post", "index": index},
        )
    return processed


def _save_post(
    post: instaloader.Post,
    parent_dir: Path,
    *,
    options: DownloadOptions,
    client: InstagramClient,
    report: DownloadReport,
) -> None:
    post_dir = parent_dir / post.shortcode
    post_dir.mkdir(parents=True, exist_ok=True)

    media_refs = _collect_media_urls(post)
    assets_list: list[dict[str, Any]] = []
    if options.download_images:
        for ref in media_refs:
            local = _download_media(ref["abs_url"], post_dir, kind="images")
            if local is not None:
                ref["local_path"] = local
                ref["sha256"] = _file_sha(post_dir / local)
                report.images_downloaded += 1
            assets_list.append(ref)
    else:
        assets_list = media_refs

    metadata = _post_metadata(post)
    comments_payload: list[dict[str, Any]] = []
    if options.fetch_comments and client.logged_in_as is not None:
        try:
            comments_payload = _collect_comments(post)
            report.comments_collected += len(comments_payload)
        except Exception as exc:
            report.errors.append(f"comments {post.shortcode}: {exc}")

    content_md = _render_post_md(post, metadata=metadata, asset_count=len(assets_list))
    (post_dir / "content.md").write_text(content_md, encoding="utf-8")
    (post_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    (post_dir / "assets.json").write_text(
        json.dumps(assets_list, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (post_dir / "comments.json").write_text(
        json.dumps(comments_payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def _walk_highlights(
    client: InstagramClient,
    profile: instaloader.Profile,
    target_root: Path,
    *,
    report: DownloadReport,
    options: DownloadOptions,
    on_progress: Callable[[str, dict[str, Any]], None] | None,
) -> None:
    highlights_dir = target_root / "highlights"
    highlights_dir.mkdir(parents=True, exist_ok=True)
    try:
        iterator = client.loader.get_highlights(user=profile)
    except Exception as exc:
        report.errors.append(f"highlights: {exc}")
        return
    for hl in iterator:
        title = _slug(getattr(hl, "title", "untitled") or "untitled")
        hl_dir = highlights_dir / title
        hl_dir.mkdir(parents=True, exist_ok=True)
        meta = {"id": hl.unique_id, "title": hl.title, "items": []}
        item_count = 0
        for item in hl.get_items():
            item_dir = hl_dir / str(item.mediaid)
            item_dir.mkdir(parents=True, exist_ok=True)
            url = item.url
            local = _download_media(url, item_dir, kind="images") if options.download_images else None
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
                f"url: \"ig://highlight/{hl.unique_id}/{item.mediaid}\"\n"
                f"fetched_at: \"{datetime.now(UTC).isoformat()}\"\n"
                f"---\n\n"
                f"# {hl.title}\n\n"
                f"Highlight item from {item.date_utc.isoformat()}\n",
                encoding="utf-8",
            )
            meta["items"].append({"mediaid": item.mediaid, "date": item.date_utc.isoformat()})
            item_count += 1
            if local is not None:
                report.images_downloaded += 1
        (hl_dir / "highlight.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
        )
        report.highlights += item_count
        _emit(on_progress, "highlight_saved", {"title": hl.title, "items": item_count})


def _walk_stories(
    client: InstagramClient,
    profile: instaloader.Profile,
    target_root: Path,
    *,
    report: DownloadReport,
    options: DownloadOptions,
    on_progress: Callable[[str, dict[str, Any]], None] | None,
) -> None:
    stories_dir = target_root / "stories"
    stories_dir.mkdir(parents=True, exist_ok=True)
    try:
        iterator = client.loader.get_stories(userids=[profile.userid])
    except Exception as exc:
        report.errors.append(f"stories: {exc}")
        return
    for story in iterator:
        for item in story.get_items():
            item_dir = stories_dir / str(item.mediaid)
            item_dir.mkdir(parents=True, exist_ok=True)
            url = item.url
            local = _download_media(url, item_dir, kind="images") if options.download_images else None
            (item_dir / "assets.json").write_text(
                json.dumps(
                    [{"kind": "image", "abs_url": url, "local_path": local}],
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (item_dir / "content.md").write_text(
                f"---\n"
                f'title: "story"\n'
                f"url: \"ig://story/{item.mediaid}\"\n"
                f"---\n\n# Story {item.mediaid}\n\nFrom {item.date_utc.isoformat()}\n",
                encoding="utf-8",
            )
            report.stories += 1
            if local is not None:
                report.images_downloaded += 1
            _emit(on_progress, "story_saved", {"mediaid": item.mediaid})


def _collect_media_urls(post: instaloader.Post) -> list[dict[str, Any]]:
    """Image URLs for the post / each carousel slide. Skips videos by design."""
    media: list[dict[str, Any]] = []
    if post.typename == "GraphSidecar":
        for slide in post.get_sidecar_nodes():
            if slide.is_video:
                continue
            media.append({"kind": "image", "abs_url": slide.display_url, "alt": ""})
    elif post.is_video:
        # Reel / video — only keep the cover frame.
        media.append({"kind": "image", "abs_url": post.url, "alt": "cover", "is_video_cover": True})
    else:
        media.append({"kind": "image", "abs_url": post.url, "alt": ""})
    return media


def _post_metadata(post: instaloader.Post) -> dict[str, Any]:
    return {
        "shortcode": post.shortcode,
        "url": f"https://www.instagram.com/p/{post.shortcode}/",
        "owner_username": post.owner_username,
        "is_video": post.is_video,
        "typename": post.typename,
        "date_utc": post.date_utc.isoformat() if post.date_utc else None,
        "caption": post.caption,
        "likes": post.likes,
        "comments_count": post.comments,
        "video_view_count": getattr(post, "video_view_count", None),
        "location": _location_dict(post),
        "hashtags": sorted(set(post.caption_hashtags or [])),
        "mentions": sorted(set(post.caption_mentions or [])),
        "tagged_users": _tagged_users(post),
    }


def _location_dict(post: instaloader.Post) -> dict[str, Any] | None:
    loc = getattr(post, "location", None)
    if loc is None:
        return None
    try:
        return {"id": getattr(loc, "id", None), "name": getattr(loc, "name", None)}
    except Exception:
        return None


def _tagged_users(post: instaloader.Post) -> list[str]:
    try:
        return list(post.tagged_users)
    except Exception:
        return []


def _collect_comments(post: instaloader.Post) -> list[dict[str, Any]]:
    comments: list[dict[str, Any]] = []
    for comment in post.get_comments():
        replies: list[dict[str, Any]] = []
        for reply in getattr(comment, "answers", []) or []:
            replies.append(
                {
                    "owner": getattr(reply.owner, "username", "?"),
                    "text": reply.text,
                    "likes": getattr(reply, "likes_count", 0),
                    "created_at": reply.created_at_utc.isoformat() if reply.created_at_utc else None,
                }
            )
        comments.append(
            {
                "owner": getattr(comment.owner, "username", "?"),
                "text": comment.text,
                "likes": getattr(comment, "likes_count", 0),
                "created_at": comment.created_at_utc.isoformat() if comment.created_at_utc else None,
                "replies": replies,
            }
        )
    return comments


def _render_post_md(
    post: instaloader.Post,
    *,
    metadata: dict[str, Any],
    asset_count: int,
) -> str:
    title = (post.caption or post.shortcode).strip().splitlines()[0][:80] or post.shortcode
    lines = [
        "---",
        f'url: "https://www.instagram.com/p/{post.shortcode}/"',
        f'final_url: "https://www.instagram.com/p/{post.shortcode}/"',
        f'title: "{_yaml_escape(title)}"',
        f'fetched_at: "{datetime.now(UTC).isoformat()}"',
        "status_code: 200",
        'tier: "instagram"',
        f"likes: {metadata.get('likes', 0)}",
        f"comments_count: {metadata.get('comments_count', 0)}",
        f"is_video: {str(post.is_video).lower()}",
        f"images: {asset_count}",
        "---",
        "",
        f"# {title}",
        "",
        f"_posted by **@{post.owner_username}** on {post.date_utc.isoformat() if post.date_utc else '?'}_",
        "",
        f"❤ {metadata.get('likes', 0)}  ·  💬 {metadata.get('comments_count', 0)}",
        "",
    ]
    if post.caption:
        lines.append(post.caption)
        lines.append("")
    if metadata.get("hashtags"):
        lines.append("**Hashtags:** " + " ".join(f"#{h}" for h in metadata["hashtags"]))
        lines.append("")
    if metadata.get("mentions"):
        lines.append("**Mentions:** " + " ".join(f"@{m}" for m in metadata["mentions"]))
        lines.append("")
    location = metadata.get("location")
    if location and location.get("name"):
        lines.append(f"**Location:** {location['name']}")
        lines.append("")
    return "\n".join(lines) + "\n"


def _yaml_escape(text: str) -> str:
    return text.replace('"', '\\"')


def _serialize_profile(profile: instaloader.Profile) -> dict[str, Any]:
    return {
        "username": profile.username,
        "userid": profile.userid,
        "full_name": profile.full_name,
        "biography": profile.biography,
        "followers": profile.followers,
        "followees": profile.followees,
        "media_count": profile.mediacount,
        "is_private": profile.is_private,
        "is_verified": profile.is_verified,
        "external_url": profile.external_url,
        "profile_pic_url": profile.profile_pic_url,
    }


def _download_media(url: str, page_dir: Path, *, kind: str) -> str | None:
    """Synchronous httpx download to keep parity with instaloader's blocking API."""
    images_dir = page_dir / "assets" / kind
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
    rel = target.relative_to(page_dir)
    return str(rel).replace("\\", "/")


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
    """Async wrapper — instaloader is sync, so we run it on a worker thread."""
    return await asyncio.to_thread(
        download_profile,
        client,
        username,
        out_root=out_root,
        options=options,
        on_progress=on_progress,
    )
