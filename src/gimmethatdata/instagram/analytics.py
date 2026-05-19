"""Engagement analytics over a downloaded Instagram profile.

Walks the same `<out>/instagram/<user>/` tree we already write — reads
`profile.json`, every post's `metadata.json`, and produces:

  _engagement_report.md
  _engagement_report.json

Numbers come only from data already on disk; no extra IG API calls.
"""

from __future__ import annotations

import itertools
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z']+")
_HASHTAG_RE = re.compile(r"(?<![\w])#([A-Za-z0-9_]+)")
_MENTION_RE = re.compile(r"(?<![\w])@([A-Za-z0-9._]+)")

_STOPWORDS: frozenset[str] = frozenset([
    "a", "an", "the", "and", "or", "but", "if", "then", "so", "of", "in",
    "on", "at", "by", "for", "to", "from", "with", "into", "onto", "upon",
    "as", "is", "are", "was", "were", "be", "been", "being", "have", "has",
    "had", "do", "does", "did", "i", "me", "my", "we", "our", "you", "your",
    "he", "she", "it", "they", "them", "their", "this", "that", "these",
    "those", "there", "here", "just", "like", "really", "very", "some",
    "all", "any", "no", "not", "yes", "will", "would", "can", "could",
    "should", "may", "might", "also", "too", "only", "out", "over", "off",
    "up", "down", "about", "again", "own", "same", "than", "such", "who",
    "what", "whom", "which", "one", "two", "three", "more", "most", "much",
])


@dataclass
class PostStat:
    shortcode: str
    kind: str  # "post" or "reel"
    caption: str
    likes: int
    comments: int
    plays: int
    taken_at: datetime | None
    hashtags: list[str]
    mentions: list[str]


@dataclass
class EngagementReport:
    profile_root: Path
    username: str
    follower_count: int
    media_count: int
    posts: list[PostStat]
    reels: list[PostStat]
    top_caption_words: list[tuple[str, int]]
    top_caption_bigrams: list[tuple[str, int]]
    own_hashtags: list[tuple[str, int]]
    own_mentions: list[tuple[str, int]]
    posting_heatmap: dict[int, dict[int, int]]  # dow -> hour -> count
    daily_engagement: list[tuple[str, int, int]]  # (date, likes, comments)

    @property
    def total_posts(self) -> int:
        return len(self.posts) + len(self.reels)

    def averages(self) -> dict[str, float]:
        return {
            "posts_avg_likes": _avg([p.likes for p in self.posts]),
            "posts_avg_comments": _avg([p.comments for p in self.posts]),
            "reels_avg_likes": _avg([r.likes for r in self.reels]),
            "reels_avg_comments": _avg([r.comments for r in self.reels]),
            "reels_avg_plays": _avg([r.plays for r in self.reels if r.plays]),
            "engagement_rate_pct": (
                100.0
                * sum(p.likes + p.comments for p in self.posts + self.reels)
                / max(1, self.follower_count * self.total_posts)
            ),
        }

    def best_by(self, *, metric: str, top: int = 10, kind: str | None = None) -> list[PostStat]:
        pool = self.posts + self.reels
        if kind == "post":
            pool = self.posts
        elif kind == "reel":
            pool = self.reels
        key = {
            "likes": lambda p: p.likes,
            "comments": lambda p: p.comments,
            "plays": lambda p: p.plays,
            "engagement": lambda p: p.likes + p.comments,
        }[metric]
        return sorted(pool, key=key, reverse=True)[:top]

    def worst_by_engagement(self, *, top: int = 10) -> list[PostStat]:
        return sorted(self.posts + self.reels, key=lambda p: p.likes + p.comments)[:top]

    def as_dict(self) -> dict[str, Any]:
        return {
            "username": self.username,
            "follower_count": self.follower_count,
            "media_count": self.media_count,
            "totals": {
                "posts": len(self.posts),
                "reels": len(self.reels),
            },
            "averages": self.averages(),
            "top_caption_words": _pairs(self.top_caption_words),
            "top_caption_bigrams": _pairs(self.top_caption_bigrams),
            "own_hashtags": _pairs(self.own_hashtags),
            "own_mentions": _pairs(self.own_mentions),
            "best_by_likes": [_stat_dict(p) for p in self.best_by(metric="likes")],
            "best_by_comments": [_stat_dict(p) for p in self.best_by(metric="comments")],
            "best_by_engagement": [_stat_dict(p) for p in self.best_by(metric="engagement")],
            "worst_by_engagement": [_stat_dict(p) for p in self.worst_by_engagement()],
            "posting_heatmap": {
                str(dow): {str(h): n for h, n in hours.items()}
                for dow, hours in self.posting_heatmap.items()
            },
            "daily_engagement": [
                {"date": d, "likes": likes, "comments": comments}
                for d, likes, comments in self.daily_engagement
            ],
        }


def _pairs(items: list[tuple[str, int]]) -> list[dict[str, Any]]:
    return [{"key": k, "count": v} for k, v in items]


def _stat_dict(stat: PostStat) -> dict[str, Any]:
    return {
        "shortcode": stat.shortcode,
        "kind": stat.kind,
        "likes": stat.likes,
        "comments": stat.comments,
        "plays": stat.plays,
        "taken_at": stat.taken_at.isoformat() if stat.taken_at else None,
        "caption_first_line": (stat.caption or "").splitlines()[0][:120] if stat.caption else "",
    }


def analyze(profile_root: Path, *, top_n: int = 25) -> EngagementReport:
    profile = _read_profile(profile_root)
    username = str(profile.get("username") or profile_root.name)
    follower_count = int(profile.get("followers") or 0)
    media_count = int(profile.get("media_count") or 0)

    posts: list[PostStat] = []
    reels: list[PostStat] = []
    for kind, subdir in (("post", "posts"), ("reel", "reels")):
        for metadata_path in sorted((profile_root / subdir).rglob("metadata.json")):
            stat = _load_stat(metadata_path, kind=kind)
            if stat is None:
                continue
            (reels if kind == "reel" else posts).append(stat)

    words: Counter[str] = Counter()
    bigrams: Counter[str] = Counter()
    own_hashtags: Counter[str] = Counter()
    own_mentions: Counter[str] = Counter()
    for caption in (p.caption for p in posts + reels if p.caption):
        tokens = [t.lower() for t in _WORD_RE.findall(caption) if t.lower() not in _STOPWORDS]
        words.update(tokens)
        for a, b in itertools.pairwise(tokens):
            if len(a) > 2 and len(b) > 2:
                bigrams[f"{a} {b}"] += 1
        for tag in _HASHTAG_RE.findall(caption):
            own_hashtags[tag.lower()] += 1
        for mention in _MENTION_RE.findall(caption):
            own_mentions[mention.lower()] += 1

    heatmap: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    timeline_acc: dict[str, dict[str, int]] = defaultdict(lambda: {"likes": 0, "comments": 0})
    for stat in posts + reels:
        if stat.taken_at is None:
            continue
        local = stat.taken_at
        heatmap[local.weekday()][local.hour] += 1
        day = local.date().isoformat()
        timeline_acc[day]["likes"] += stat.likes
        timeline_acc[day]["comments"] += stat.comments

    daily = sorted(
        (
            (date, payload["likes"], payload["comments"])
            for date, payload in timeline_acc.items()
        )
    )

    return EngagementReport(
        profile_root=profile_root,
        username=username,
        follower_count=follower_count,
        media_count=media_count,
        posts=posts,
        reels=reels,
        top_caption_words=words.most_common(top_n),
        top_caption_bigrams=bigrams.most_common(top_n),
        own_hashtags=own_hashtags.most_common(top_n),
        own_mentions=own_mentions.most_common(top_n),
        posting_heatmap={dow: dict(hours) for dow, hours in heatmap.items()},
        daily_engagement=daily,
    )


def _avg(values: list[int]) -> float:
    return sum(values) / len(values) if values else 0.0


def _read_profile(profile_root: Path) -> dict[str, Any]:
    profile_path = profile_root / "profile.json"
    if not profile_path.exists():
        return {}
    try:
        data = json.loads(profile_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _load_stat(metadata_path: Path, *, kind: str) -> PostStat | None:
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    raw_taken = payload.get("taken_at")
    taken_at: datetime | None = None
    if isinstance(raw_taken, str):
        try:
            taken_at = datetime.fromisoformat(raw_taken)
            if taken_at.tzinfo is None:
                taken_at = taken_at.replace(tzinfo=UTC)
        except ValueError:
            taken_at = None
    return PostStat(
        shortcode=str(payload.get("shortcode") or metadata_path.parent.name),
        kind=kind,
        caption=str(payload.get("caption") or ""),
        likes=int(payload.get("likes") or 0),
        comments=int(payload.get("comments_count") or 0),
        plays=int(
            payload.get("play_count")
            or payload.get("video_view_count")
            or 0
        ),
        taken_at=taken_at,
        hashtags=list(payload.get("hashtags") or []),
        mentions=list(payload.get("mentions") or []),
    )


def render_markdown(report: EngagementReport) -> str:
    avg = report.averages()
    lines = [
        f"# Engagement insights — @{report.username}",
        "",
        f"Generated: `{datetime.now(UTC).isoformat()}`",
        "",
        "## Overview",
        "",
        f"- Followers (snapshot): **{report.follower_count:,}**",
        f"- Media on profile: **{report.media_count}**",
        f"- Posts analyzed: **{len(report.posts)}**  ·  Reels analyzed: **{len(report.reels)}**",
        f"- Avg likes / post: **{avg['posts_avg_likes']:.1f}**",
        f"- Avg comments / post: **{avg['posts_avg_comments']:.1f}**",
        f"- Avg likes / reel: **{avg['reels_avg_likes']:.1f}**",
        f"- Avg comments / reel: **{avg['reels_avg_comments']:.1f}**",
        f"- Avg plays / reel: **{avg['reels_avg_plays']:.0f}**",
        f"- Engagement rate: **{avg['engagement_rate_pct']:.2f}%** ((likes+comments) / (followers x posts))",
        "",
    ]
    if report.posts and report.reels:
        ratio = (
            avg["reels_avg_likes"] / avg["posts_avg_likes"]
            if avg["posts_avg_likes"]
            else 0.0
        )
        lines.append(
            f"_Reels pull about **{ratio:.2f}x** the average likes of static posts._"
        )
        lines.append("")

    lines.extend(_leaderboard("Top by likes", report.best_by(metric="likes")))
    lines.extend(_leaderboard("Top by comments", report.best_by(metric="comments")))
    lines.extend(
        _leaderboard("Top by total engagement (likes + comments)", report.best_by(metric="engagement"))
    )
    lines.extend(
        _leaderboard("Quietest posts", report.worst_by_engagement(), reverse=False)
    )

    lines.append("## Posting heatmap (day-of-week x hour)")
    lines.append("")
    lines.append("```")
    lines.append(_render_heatmap(report.posting_heatmap))
    lines.append("```")
    lines.append("")

    lines.append("## Daily engagement (last 60 dated days)")
    lines.append("")
    lines.append("```")
    lines.append(_render_daily(report.daily_engagement[-60:]))
    lines.append("```")
    lines.append("")

    lines.extend(_table_section("Their own hashtags", report.own_hashtags))
    lines.extend(_table_section("Their own mentions", report.own_mentions))
    lines.extend(_table_section("Caption vocabulary (top words)", report.top_caption_words))
    lines.extend(_table_section("Caption phrases (bigrams)", report.top_caption_bigrams))
    return "\n".join(lines)


def _leaderboard(title: str, items: list[PostStat], reverse: bool = True) -> list[str]:
    if not items:
        return []
    out = [f"## {title}", "", "| # | shortcode | kind | ❤ | 💬 | ▶ | first line |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for i, stat in enumerate(items, start=1):
        first = (stat.caption or "").splitlines()
        snippet = (first[0][:60] if first else "").replace("|", "\\|")
        out.append(
            f"| {i} | `{stat.shortcode}` | {stat.kind} | {stat.likes:,} | "
            f"{stat.comments} | {stat.plays or '-'} | {snippet} |"
        )
    out.append("")
    return out


def _render_heatmap(heatmap: dict[int, dict[int, int]]) -> str:
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    max_count = max(
        (n for hours in heatmap.values() for n in hours.values()), default=1
    )
    rows = ["         " + " ".join(f"{h:>2}" for h in range(24))]
    for dow in range(7):
        cells = []
        for hour in range(24):
            count = heatmap.get(dow, {}).get(hour, 0)
            cells.append(_glyph(count, max_count))
        rows.append(f"  {days[dow]}    " + " ".join(cells))
    return "\n".join(rows)


def _glyph(count: int, max_count: int) -> str:
    if count == 0:
        return " ·"
    ratio = count / max_count
    if ratio >= 0.75:
        return "##"
    if ratio >= 0.5:
        return "**"
    if ratio >= 0.25:
        return "::"
    return " ."


def _render_daily(rows: list[tuple[str, int, int]]) -> str:
    if not rows:
        return "(no dated posts)"
    max_engagement = max(likes + comments for _, likes, comments in rows) or 1
    lines = []
    for date, likes, comments in rows:
        engagement = likes + comments
        bar = "#" * max(1, int(engagement / max_engagement * 40))
        lines.append(f"{date}  ❤{likes:>5}  💬{comments:>3}  {bar}")
    return "\n".join(lines)


def _table_section(title: str, items: list[tuple[str, int]]) -> list[str]:
    if not items:
        return []
    out = [f"## {title}", "", "| # | Key | Count |", "| --- | --- | --- |"]
    for i, (key, count) in enumerate(items, start=1):
        out.append(f"| {i} | {key} | {count} |")
    out.append("")
    return out


def write_report(report: EngagementReport) -> tuple[Path, Path]:
    md_path = report.profile_root / "_engagement_report.md"
    json_path = report.profile_root / "_engagement_report.json"
    md_path.write_text(render_markdown(report), encoding="utf-8")
    json_path.write_text(
        json.dumps(report.as_dict(), indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return md_path, json_path
