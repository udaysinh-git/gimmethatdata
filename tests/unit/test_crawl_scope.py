"""Tests for crawl/frontier scope rules + frontier sqlite behaviour."""

from __future__ import annotations

from pathlib import Path

import pytest

from gimmethatdata.crawl.frontier import Frontier, FrontierStatus, ScopeMode, ScopeRule


def test_same_domain_includes_subdomains() -> None:
    rule = ScopeRule(seed="https://example.com/", mode=ScopeMode.SAME_DOMAIN)
    assert rule.includes("https://example.com/x")
    assert rule.includes("https://blog.example.com/y")
    assert not rule.includes("https://evil-example.com/y")  # suffix-match guard
    assert not rule.includes("https://other.com/")


def test_same_host_strict() -> None:
    rule = ScopeRule(seed="https://example.com/", mode=ScopeMode.SAME_HOST)
    assert rule.includes("https://example.com/x")
    assert not rule.includes("https://www.example.com/x")


def test_allowlist_with_deny() -> None:
    rule = ScopeRule(
        seed="https://example.com/",
        mode=ScopeMode.ALLOWLIST,
        allow_patterns=["https://example.com/blog/*"],
        deny_patterns=["https://example.com/blog/private/*"],
    )
    assert rule.includes("https://example.com/blog/post-1")
    assert not rule.includes("https://example.com/blog/private/x")
    assert not rule.includes("https://example.com/about")


@pytest.mark.asyncio
async def test_frontier_dedup_and_claim_order(tmp_path: Path) -> None:
    frontier = Frontier(tmp_path / "site.sqlite")
    await frontier.open()
    try:
        await frontier.add([("https://example.com/a", 0, None)])
        added_again = await frontier.add([("https://example.com/a", 0, None)])
        assert added_again == 0
        await frontier.add(
            [
                ("https://example.com/b", 1, "https://example.com/a"),
                ("https://example.com/c", 2, "https://example.com/a"),
            ]
        )
        claimed_first = await frontier.claim_next()
        assert claimed_first is not None
        assert claimed_first[0] == "https://example.com/a"
        await frontier.mark(claimed_first[0], FrontierStatus.DONE)

        claimed_second = await frontier.claim_next()
        assert claimed_second is not None
        assert claimed_second[1] == 1  # next-shallowest first
    finally:
        await frontier.close()
