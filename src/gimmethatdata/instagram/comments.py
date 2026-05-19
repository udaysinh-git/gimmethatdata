"""Aggregate Instagram comments across a downloaded profile into an insights
report. Reads every `comments.json` under `<profile_root>/posts` and `reels`,
produces both a JSON dump and a human-readable Markdown report.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_HASHTAG_RE = re.compile(r"(?<![\w])#([A-Za-z0-9_]+)")
_MENTION_RE = re.compile(r"(?<![\w])@([A-Za-z0-9._]+)")
_EMOJI_RE = re.compile(
    "[\U0001f300-\U0001faff\U00002600-\U000027bf\U0001f1e6-\U0001f1ff]",
)


@dataclass
class CommentInsights:
    profile_root: Path
    total_posts: int
    total_comments: int
    total_replies: int
    unique_commenters: int
    top_commenters: list[tuple[str, int]]
    top_hashtags: list[tuple[str, int]]
    top_mentions: list[tuple[str, int]]
    top_emojis: list[tuple[str, int]]
    busiest_posts: list[tuple[str, int]]  # (shortcode, comment_count)
    most_liked_comments: list[dict[str, Any]]
    daily_timeline: list[tuple[str, int]]  # (YYYY-MM-DD, count)
    average_comments_per_post: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "profile_root": str(self.profile_root),
            "totals": {
                "posts": self.total_posts,
                "comments": self.total_comments,
                "replies": self.total_replies,
                "unique_commenters": self.unique_commenters,
                "average_comments_per_post": round(self.average_comments_per_post, 2),
            },
            "top_commenters": _pairs(self.top_commenters),
            "top_hashtags": _pairs(self.top_hashtags),
            "top_mentions": _pairs(self.top_mentions),
            "top_emojis": _pairs(self.top_emojis),
            "busiest_posts": _pairs(self.busiest_posts),
            "most_liked_comments": self.most_liked_comments,
            "daily_timeline": _pairs(self.daily_timeline),
        }


def _pairs(items: list[tuple[str, int]]) -> list[dict[str, int | str]]:
    return [{"key": k, "count": v} for k, v in items]


def analyze(profile_root: Path, *, top_n: int = 25) -> CommentInsights:
    """Walk every `comments.json` under the profile root and aggregate."""
    posts_seen: list[tuple[str, int]] = []
    total_comments = 0
    total_replies = 0
    commenters: Counter[str] = Counter()
    hashtags: Counter[str] = Counter()
    mentions: Counter[str] = Counter()
    emojis: Counter[str] = Counter()
    timeline: defaultdict[str, int] = defaultdict(int)
    most_liked: list[dict[str, Any]] = []

    for comments_path in sorted(profile_root.rglob("comments.json")):
        shortcode = comments_path.parent.name
        try:
            payload = json.loads(comments_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, list):
            continue
        post_count = 0
        for comment in payload:
            if not isinstance(comment, dict):
                continue
            owner = str(comment.get("owner") or "?")
            text = str(comment.get("text") or "")
            commenters[owner] += 1
            for tag in _HASHTAG_RE.findall(text):
                hashtags[tag.lower()] += 1
            for mention in _MENTION_RE.findall(text):
                mentions[mention.lower()] += 1
            for ch in _EMOJI_RE.findall(text):
                emojis[ch] += 1
            day = _date_key(comment.get("created_at"))
            if day:
                timeline[day] += 1
            most_liked.append(
                {
                    "owner": owner,
                    "text": text,
                    "likes": int(comment.get("likes") or 0),
                    "shortcode": shortcode,
                    "created_at": comment.get("created_at"),
                }
            )
            total_comments += 1
            post_count += 1
            for reply in comment.get("replies") or []:
                if not isinstance(reply, dict):
                    continue
                r_owner = str(reply.get("owner") or "?")
                r_text = str(reply.get("text") or "")
                commenters[r_owner] += 1
                for tag in _HASHTAG_RE.findall(r_text):
                    hashtags[tag.lower()] += 1
                for mention in _MENTION_RE.findall(r_text):
                    mentions[mention.lower()] += 1
                day = _date_key(reply.get("created_at"))
                if day:
                    timeline[day] += 1
                total_replies += 1
        posts_seen.append((shortcode, post_count))

    most_liked.sort(key=lambda c: c["likes"], reverse=True)
    busiest = sorted(posts_seen, key=lambda r: r[1], reverse=True)[:top_n]

    return CommentInsights(
        profile_root=profile_root,
        total_posts=len(posts_seen),
        total_comments=total_comments,
        total_replies=total_replies,
        unique_commenters=len(commenters),
        top_commenters=commenters.most_common(top_n),
        top_hashtags=hashtags.most_common(top_n),
        top_mentions=mentions.most_common(top_n),
        top_emojis=emojis.most_common(top_n),
        busiest_posts=busiest,
        most_liked_comments=most_liked[:top_n],
        daily_timeline=sorted(timeline.items()),
        average_comments_per_post=(
            total_comments / len(posts_seen) if posts_seen else 0.0
        ),
    )


def render_markdown(insights: CommentInsights) -> str:
    lines = [
        f"# Comment insights — {insights.profile_root.name}",
        "",
        f"Generated: `{datetime.now(UTC).isoformat()}`",
        "",
        "## Totals",
        "",
        f"- Posts inspected: **{insights.total_posts}**",
        f"- Comments collected: **{insights.total_comments:,}**",
        f"- Replies collected: **{insights.total_replies:,}**",
        f"- Unique commenters: **{insights.unique_commenters:,}**",
        f"- Average comments per post: **{insights.average_comments_per_post:.1f}**",
        "",
    ]
    lines.extend(_table_section("Top commenters", insights.top_commenters))
    lines.extend(_table_section("Top hashtags in comments", insights.top_hashtags))
    lines.extend(_table_section("Top mentions in comments", insights.top_mentions))
    lines.extend(_table_section("Top emojis", insights.top_emojis))
    lines.extend(_table_section("Busiest posts", insights.busiest_posts))

    if insights.most_liked_comments:
        lines.append("## Most-liked comments")
        lines.append("")
        lines.append("| Likes | User | Post | Comment |")
        lines.append("| --- | --- | --- | --- |")
        for entry in insights.most_liked_comments:
            text = (entry.get("text") or "").replace("\n", " ").replace("|", "\\|")[:160]
            lines.append(
                f"| {entry.get('likes', 0)} | @{entry.get('owner', '?')} | "
                f"`{entry.get('shortcode', '?')}` | {text} |"
            )
        lines.append("")

    if insights.daily_timeline:
        lines.append("## Daily comment volume (most recent 60 days)")
        lines.append("")
        lines.append("```")
        recent = insights.daily_timeline[-60:]
        max_count = max((c for _, c in recent), default=1)
        for day, count in recent:
            bar = "#" * max(1, int(count / max_count * 40))
            lines.append(f"{day}  {count:>5}  {bar}")
        lines.append("```")
        lines.append("")

    return "\n".join(lines)


def _table_section(title: str, items: list[tuple[str, int]]) -> list[str]:
    if not items:
        return []
    out = [f"## {title}", "", "| # | Key | Count |", "| --- | --- | --- |"]
    for index, (key, count) in enumerate(items, start=1):
        out.append(f"| {index} | {key} | {count} |")
    out.append("")
    return out


def write_report(insights: CommentInsights) -> tuple[Path, Path]:
    """Emit both JSON + Markdown reports next to the profile."""
    md_path = insights.profile_root / "_comments_report.md"
    json_path = insights.profile_root / "_comments_report.json"
    md_path.write_text(render_markdown(insights), encoding="utf-8")
    json_path.write_text(
        json.dumps(insights.as_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return md_path, json_path


def _date_key(raw: object) -> str | None:
    if not isinstance(raw, str) or len(raw) < 10:
        return None
    return raw[:10]
