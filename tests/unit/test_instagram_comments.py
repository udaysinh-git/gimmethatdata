"""Tests for instagram/comments analyzer."""

from __future__ import annotations

import json
from pathlib import Path

from gimmethatdata.instagram.comments import analyze, render_markdown, write_report


def _seed_post(root: Path, shortcode: str, comments: list[dict]) -> None:
    post_dir = root / "posts" / shortcode
    post_dir.mkdir(parents=True, exist_ok=True)
    (post_dir / "comments.json").write_text(
        json.dumps(comments), encoding="utf-8"
    )


def test_analyze_aggregates_across_posts(tmp_path: Path) -> None:
    profile = tmp_path / "ig" / "udaysinh"
    _seed_post(
        profile,
        "AAA",
        [
            {
                "owner": "alice",
                "text": "Love this! #ai 🚀",
                "likes": 5,
                "created_at": "2026-05-19T10:00:00",
                "replies": [
                    {
                        "owner": "bob",
                        "text": "Agreed! @alice 🚀",
                        "likes": 1,
                        "created_at": "2026-05-19T10:05:00",
                    }
                ],
            },
            {
                "owner": "alice",
                "text": "Round two #ai",
                "likes": 2,
                "created_at": "2026-05-19T11:00:00",
                "replies": [],
            },
        ],
    )
    _seed_post(
        profile,
        "BBB",
        [
            {
                "owner": "carol",
                "text": "🔥🔥🔥 amazing",
                "likes": 10,
                "created_at": "2026-05-20T09:00:00",
                "replies": [],
            },
        ],
    )

    insights = analyze(profile)
    assert insights.total_posts == 2
    assert insights.total_comments == 3
    assert insights.total_replies == 1
    assert insights.unique_commenters == 3
    assert insights.top_commenters[0] == ("alice", 2)
    assert ("ai", 2) in insights.top_hashtags
    assert ("alice", 1) in insights.top_mentions
    assert insights.busiest_posts[0][0] == "AAA"
    assert insights.most_liked_comments[0]["owner"] == "carol"


def test_render_markdown_contains_headers(tmp_path: Path) -> None:
    profile = tmp_path / "ig" / "x"
    _seed_post(
        profile,
        "z",
        [{"owner": "u", "text": "hi", "likes": 0, "created_at": "2026-05-19T10:00:00", "replies": []}],
    )
    md = render_markdown(analyze(profile))
    assert "Comment insights" in md
    assert "Top commenters" in md
    assert "Daily comment volume" in md


def test_write_report_emits_both_files(tmp_path: Path) -> None:
    profile = tmp_path / "ig" / "x"
    _seed_post(
        profile,
        "z",
        [{"owner": "u", "text": "hi", "likes": 0, "created_at": "2026-05-19T10:00:00", "replies": []}],
    )
    insights = analyze(profile)
    md_path, json_path = write_report(insights)
    assert md_path.exists()
    assert json_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["totals"]["comments"] == 1


def test_analyze_empty_profile(tmp_path: Path) -> None:
    profile = tmp_path / "ig" / "empty"
    profile.mkdir(parents=True)
    insights = analyze(profile)
    assert insights.total_posts == 0
    assert insights.total_comments == 0
    assert insights.average_comments_per_post == 0.0
