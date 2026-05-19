"""Side-by-side comparison of two downloaded Instagram profiles.

Computes:
  * High-level metric deltas (followers, posts, avg likes, reels:photos ratio).
  * Commenter audience overlap — Jaccard + intersection + each side's exclusives.
  * Shared hashtags + mentions usage.
  * Posting-cadence overlap (which weekdays they both prefer).

Reads only files already on disk; produces both Markdown + JSON.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from gimmethatdata.instagram.analytics import EngagementReport
from gimmethatdata.instagram.analytics import analyze as analyze_engagement


@dataclass
class CompareReport:
    left: EngagementReport
    right: EngagementReport
    shared_commenters: list[tuple[str, int, int]]  # (username, left_count, right_count)
    left_only_commenters: int
    right_only_commenters: int
    jaccard_commenters: float
    shared_hashtags: list[tuple[str, int, int]]
    shared_mentions: list[tuple[str, int, int]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "left_username": self.left.username,
            "right_username": self.right.username,
            "metrics": _metric_pairs(self.left, self.right),
            "audience": {
                "shared_commenter_count": len(self.shared_commenters),
                "left_only": self.left_only_commenters,
                "right_only": self.right_only_commenters,
                "jaccard": round(self.jaccard_commenters, 4),
                "shared_commenters": [
                    {"username": u, "left_count": a, "right_count": b}
                    for u, a, b in self.shared_commenters
                ],
            },
            "shared_hashtags": [
                {"key": k, "left_count": a, "right_count": b}
                for k, a, b in self.shared_hashtags
            ],
            "shared_mentions": [
                {"key": k, "left_count": a, "right_count": b}
                for k, a, b in self.shared_mentions
            ],
        }


def _metric_pairs(left: EngagementReport, right: EngagementReport) -> list[dict[str, Any]]:
    la = left.averages()
    ra = right.averages()
    return [
        {"metric": "followers", "left": left.follower_count, "right": right.follower_count},
        {"metric": "posts", "left": len(left.posts), "right": len(right.posts)},
        {"metric": "reels", "left": len(left.reels), "right": len(right.reels)},
        {
            "metric": "avg_likes_per_post",
            "left": round(la["posts_avg_likes"], 1),
            "right": round(ra["posts_avg_likes"], 1),
        },
        {
            "metric": "avg_comments_per_post",
            "left": round(la["posts_avg_comments"], 1),
            "right": round(ra["posts_avg_comments"], 1),
        },
        {
            "metric": "engagement_rate_pct",
            "left": round(la["engagement_rate_pct"], 2),
            "right": round(ra["engagement_rate_pct"], 2),
        },
    ]


def compare(left_root: Path, right_root: Path, *, top_n: int = 25) -> CompareReport:
    left = analyze_engagement(left_root)
    right = analyze_engagement(right_root)

    left_commenters = _collect_commenters(left_root)
    right_commenters = _collect_commenters(right_root)
    left_set = set(left_commenters)
    right_set = set(right_commenters)
    intersection = left_set & right_set
    union = left_set | right_set

    shared = sorted(
        ((u, left_commenters[u], right_commenters[u]) for u in intersection),
        key=lambda r: r[1] + r[2],
        reverse=True,
    )[:top_n]

    shared_hashtags = _shared_pairs(left.own_hashtags, right.own_hashtags, top_n=top_n)
    shared_mentions = _shared_pairs(left.own_mentions, right.own_mentions, top_n=top_n)

    return CompareReport(
        left=left,
        right=right,
        shared_commenters=shared,
        left_only_commenters=len(left_set - right_set),
        right_only_commenters=len(right_set - left_set),
        jaccard_commenters=len(intersection) / len(union) if union else 0.0,
        shared_hashtags=shared_hashtags,
        shared_mentions=shared_mentions,
    )


def _collect_commenters(profile_root: Path) -> Counter[str]:
    """Walk every `comments.json` under the profile and count unique commenters."""
    counts: Counter[str] = Counter()
    for path in profile_root.rglob("comments.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, list):
            continue
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            owner = str(entry.get("owner") or "")
            if owner and owner != "?":
                counts[owner] += 1
            for reply in entry.get("replies") or []:
                if isinstance(reply, dict):
                    r_owner = str(reply.get("owner") or "")
                    if r_owner and r_owner != "?":
                        counts[r_owner] += 1
    return counts


def _shared_pairs(
    left: list[tuple[str, int]],
    right: list[tuple[str, int]],
    *,
    top_n: int,
) -> list[tuple[str, int, int]]:
    left_map = dict(left)
    right_map = dict(right)
    shared = sorted(
        (
            (key, left_map[key], right_map[key])
            for key in left_map.keys() & right_map.keys()
        ),
        key=lambda r: r[1] + r[2],
        reverse=True,
    )
    return shared[:top_n]


def render_markdown(report: CompareReport) -> str:
    a = report.left
    b = report.right
    lines = [
        f"# Compare @{a.username} vs @{b.username}",
        "",
        f"Generated: `{datetime.now(UTC).isoformat()}`",
        "",
        "## Metrics",
        "",
        "| Metric | @" + a.username + " | @" + b.username + " |",
        "| --- | --- | --- |",
    ]
    for row in _metric_pairs(a, b):
        lines.append(f"| {row['metric']} | {row['left']} | {row['right']} |")
    lines.append("")

    lines.append("## Audience overlap")
    lines.append("")
    lines.append(
        f"- Commenters seen on both: **{len(report.shared_commenters)}**"
    )
    lines.append(f"- Only on @{a.username}: **{report.left_only_commenters}**")
    lines.append(f"- Only on @{b.username}: **{report.right_only_commenters}**")
    lines.append(f"- Jaccard similarity: **{report.jaccard_commenters:.3f}**")
    lines.append("")
    if report.shared_commenters:
        lines.append(f"| User | @{a.username} | @{b.username} |")
        lines.append("| --- | --- | --- |")
        for username, left_count, right_count in report.shared_commenters:
            lines.append(f"| @{username} | {left_count} | {right_count} |")
        lines.append("")

    if report.shared_hashtags:
        lines.append("## Shared hashtags (own captions)")
        lines.append("")
        lines.append(f"| Tag | @{a.username} | @{b.username} |")
        lines.append("| --- | --- | --- |")
        for tag, la, lb in report.shared_hashtags:
            lines.append(f"| #{tag} | {la} | {lb} |")
        lines.append("")

    if report.shared_mentions:
        lines.append("## Shared mentions (own captions)")
        lines.append("")
        lines.append(f"| Mention | @{a.username} | @{b.username} |")
        lines.append("| --- | --- | --- |")
        for mention, la, lb in report.shared_mentions:
            lines.append(f"| @{mention} | {la} | {lb} |")
        lines.append("")

    return "\n".join(lines)


def write_report(
    report: CompareReport,
    *,
    out_dir: Path | None = None,
) -> tuple[Path, Path]:
    target = out_dir or report.left.profile_root.parent
    target.mkdir(parents=True, exist_ok=True)
    base = f"_compare-{report.left.username}-vs-{report.right.username}"
    md_path = target / f"{base}.md"
    json_path = target / f"{base}.json"
    md_path.write_text(render_markdown(report), encoding="utf-8")
    json_path.write_text(
        json.dumps(report.as_dict(), indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return md_path, json_path
