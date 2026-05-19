"""Tests for instagram/analytics, compare, contact_sheet."""

from __future__ import annotations

import json
from pathlib import Path

from gimmethatdata.instagram.analytics import analyze, render_markdown, write_report
from gimmethatdata.instagram.compare import compare
from gimmethatdata.instagram.compare import write_report as write_compare_report
from gimmethatdata.instagram.contact_sheet import build_contact_sheet, write_contact_sheet


def _seed_profile(
    profile_root: Path,
    *,
    username: str,
    followers: int = 100,
    posts: list[dict] | None = None,
    comments: dict[str, list[dict]] | None = None,
) -> None:
    profile_root.mkdir(parents=True, exist_ok=True)
    (profile_root / "profile.json").write_text(
        json.dumps(
            {
                "username": username,
                "followers": followers,
                "media_count": len(posts or []),
            }
        ),
        encoding="utf-8",
    )
    for post in posts or []:
        kind = post.get("kind", "post")
        post_dir = profile_root / ("reels" if kind == "reel" else "posts") / post["shortcode"]
        post_dir.mkdir(parents=True, exist_ok=True)
        (post_dir / "metadata.json").write_text(
            json.dumps(
                {
                    "shortcode": post["shortcode"],
                    "url": f"https://www.instagram.com/p/{post['shortcode']}/",
                    "caption": post.get("caption", ""),
                    "likes": post.get("likes", 0),
                    "comments_count": post.get("comments", 0),
                    "play_count": post.get("plays"),
                    "taken_at": post.get("taken_at", "2026-05-19T10:00:00+00:00"),
                    "media_type": 2 if kind == "reel" else 1,
                    "product_type": "clips" if kind == "reel" else "feed",
                    "hashtags": post.get("hashtags", []),
                    "mentions": post.get("mentions", []),
                }
            ),
            encoding="utf-8",
        )
        # write at least one asset
        assets = [
            {"kind": "image", "abs_url": "https://x/p.jpg", "local_path": "assets/images/x.jpg"}
        ]
        (post_dir / "assets.json").write_text(json.dumps(assets), encoding="utf-8")
        (post_dir / "content.md").write_text(
            f"---\ntitle: {post['shortcode']}\n---\n\n# {post['shortcode']}\n",
            encoding="utf-8",
        )
        # seed an image file for contact sheet
        img_dir = post_dir / "assets" / "images"
        img_dir.mkdir(parents=True, exist_ok=True)
        (img_dir / "x.jpg").write_bytes(b"fake")

        if comments and post["shortcode"] in comments:
            (post_dir / "comments.json").write_text(
                json.dumps(comments[post["shortcode"]]),
                encoding="utf-8",
            )


def test_analyze_engagement_basic(tmp_path: Path) -> None:
    profile = tmp_path / "ig" / "draftsbyuday"
    _seed_profile(
        profile,
        username="draftsbyuday",
        followers=1000,
        posts=[
            {"shortcode": "AAA", "caption": "Beach day #travel @brand", "likes": 100, "comments": 5,
             "taken_at": "2026-05-15T10:00:00+00:00"},
            {"shortcode": "BBB", "caption": "Reel time #travel", "kind": "reel", "likes": 500,
             "comments": 25, "plays": 12000, "taken_at": "2026-05-19T18:00:00+00:00"},
        ],
    )
    report = analyze(profile)
    assert report.username == "draftsbyuday"
    assert len(report.posts) == 1
    assert len(report.reels) == 1
    assert ("travel", 2) in report.own_hashtags
    assert ("brand", 1) in report.own_mentions
    assert any(stat.shortcode == "BBB" for stat in report.best_by(metric="likes"))


def test_render_engagement_markdown_has_sections(tmp_path: Path) -> None:
    profile = tmp_path / "ig" / "x"
    _seed_profile(
        profile,
        username="x",
        followers=10,
        posts=[{"shortcode": "AAA", "caption": "hi", "likes": 1, "comments": 0}],
    )
    md = render_markdown(analyze(profile))
    assert "Engagement insights" in md
    assert "Posting heatmap" in md
    assert "Daily engagement" in md


def test_write_engagement_report_emits_both(tmp_path: Path) -> None:
    profile = tmp_path / "ig" / "x"
    _seed_profile(
        profile, username="x", followers=10,
        posts=[{"shortcode": "AAA", "caption": "hi", "likes": 1, "comments": 0}],
    )
    md, json_path = write_report(analyze(profile))
    assert md.exists() and json_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["username"] == "x"


def test_compare_two_profiles_overlaps(tmp_path: Path) -> None:
    _seed_profile(
        tmp_path / "ig" / "a",
        username="a", followers=10,
        posts=[{"shortcode": "AA1", "caption": "#travel", "likes": 5, "comments": 1}],
        comments={"AA1": [
            {"owner": "alice", "text": "nice", "likes": 0, "created_at": "2026-05-19T10:00:00", "replies": []},
            {"owner": "bob", "text": "👏", "likes": 0, "created_at": "2026-05-19T10:01:00", "replies": []},
        ]},
    )
    _seed_profile(
        tmp_path / "ig" / "b",
        username="b", followers=10,
        posts=[{"shortcode": "BB1", "caption": "#travel #food", "likes": 8, "comments": 1}],
        comments={"BB1": [
            {"owner": "alice", "text": "love it", "likes": 0, "created_at": "2026-05-19T10:00:00", "replies": []},
            {"owner": "carol", "text": "✨", "likes": 0, "created_at": "2026-05-19T10:01:00", "replies": []},
        ]},
    )
    report = compare(tmp_path / "ig" / "a", tmp_path / "ig" / "b")
    shared = {entry[0] for entry in report.shared_commenters}
    assert shared == {"alice"}
    assert any(t[0] == "travel" for t in report.shared_hashtags)
    assert 0.0 < report.jaccard_commenters < 1.0


def test_write_compare_report(tmp_path: Path) -> None:
    _seed_profile(tmp_path / "a", username="a", posts=[
        {"shortcode": "AA1", "caption": "hi", "likes": 1, "comments": 0}
    ])
    _seed_profile(tmp_path / "b", username="b", posts=[
        {"shortcode": "BB1", "caption": "hi", "likes": 1, "comments": 0}
    ])
    report = compare(tmp_path / "a", tmp_path / "b")
    md, json_path = write_compare_report(report, out_dir=tmp_path)
    assert md.exists() and json_path.exists()


def test_contact_sheet_renders_html(tmp_path: Path) -> None:
    profile = tmp_path / "ig" / "user"
    _seed_profile(profile, username="user", posts=[
        {"shortcode": "P1", "caption": "first", "likes": 5, "comments": 0},
        {"shortcode": "P2", "caption": "second", "likes": 10, "comments": 1, "kind": "reel"},
    ])
    html = build_contact_sheet(profile)
    assert "<!doctype html>" in html
    assert "P1" in html
    assert "P2" in html
    assert "badge-reel" in html
    out = write_contact_sheet(profile)
    assert out.exists()
    assert "first" in out.read_text(encoding="utf-8")
