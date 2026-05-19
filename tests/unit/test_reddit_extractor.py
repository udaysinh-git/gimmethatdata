"""Tests for the Reddit extractor's URL matcher + JSON renderer."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from gimmethatdata.parse.extractors.reddit import RedditExtractor


@pytest.fixture
def extractor() -> RedditExtractor:
    return RedditExtractor()


@pytest.mark.parametrize(
    "url",
    [
        "https://www.reddit.com/r/python/comments/abc123/title-here/",
        "https://reddit.com/r/python/comments/abc123/title",
        "https://old.reddit.com/r/python/",
    ],
)
def test_matches_reddit_urls(url: str, extractor: RedditExtractor) -> None:
    assert extractor.matches(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/r/python/comments/abc123",
        "https://reddit.com/help",
        "https://reddit.com/",
    ],
)
def test_does_not_match_other_urls(url: str, extractor: RedditExtractor) -> None:
    assert not extractor.matches(url)


_THREAD_PAYLOAD = [
    {
        "data": {
            "children": [
                {
                    "data": {
                        "title": "Hello world",
                        "author": "alice",
                        "subreddit_name_prefixed": "r/python",
                        "score": 42,
                        "selftext": "Body of the post.",
                        "url": "https://reddit.com/r/python/comments/abc/",
                    }
                }
            ]
        }
    },
    {
        "data": {
            "children": [
                {
                    "kind": "t1",
                    "data": {
                        "author": "bob",
                        "body": "First comment.",
                        "score": 5,
                        "replies": {
                            "data": {
                                "children": [
                                    {
                                        "kind": "t1",
                                        "data": {
                                            "author": "carol",
                                            "body": "Nested reply.",
                                            "score": 2,
                                            "replies": "",
                                        },
                                    }
                                ]
                            }
                        },
                    },
                }
            ]
        }
    },
]


def test_extract_thread_returns_document(extractor: RedditExtractor) -> None:
    url = "https://www.reddit.com/r/python/comments/abc/hello/"
    with patch(
        "gimmethatdata.parse.extractors.reddit._fetch_json",
        return_value=_THREAD_PAYLOAD,
    ):
        doc = extractor.extract(html="<html/>", url=url)
    assert doc is not None
    assert doc.title == "Hello world"
    assert "u/alice" in doc.main_html
    assert "First comment." in doc.main_html
    assert "Nested reply." in doc.main_html
    assert doc.extra_meta is not None
    assert doc.extra_meta["reddit_score"] == "42"


def test_extract_returns_none_when_fetch_fails(extractor: RedditExtractor) -> None:
    url = "https://www.reddit.com/r/python/comments/abc/"
    with patch("gimmethatdata.parse.extractors.reddit._fetch_json", return_value=None):
        assert extractor.extract(html="<html/>", url=url) is None
