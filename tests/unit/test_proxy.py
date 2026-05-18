"""Tests for fetch/proxy."""

from __future__ import annotations

from pathlib import Path

from gimmethatdata.fetch.proxy import ProxyPool, ProxyStrategy


def test_empty_pool_returns_none() -> None:
    pool = ProxyPool([])
    assert not pool
    assert pool.pick(domain="example.com") is None


def test_round_robin_cycles() -> None:
    pool = ProxyPool(["http://a:1", "http://b:1", "http://c:1"], ProxyStrategy.ROUND_ROBIN)
    picks = [pool.pick() for _ in range(6)]
    assert picks == [
        "http://b:1",
        "http://c:1",
        "http://a:1",
        "http://b:1",
        "http://c:1",
        "http://a:1",
    ]


def test_sticky_per_domain_keeps_same_proxy() -> None:
    pool = ProxyPool(["http://a:1", "http://b:1"], ProxyStrategy.STICKY)
    first = pool.pick(domain="example.com")
    again = pool.pick(domain="example.com")
    other = pool.pick(domain="other.com")
    assert first == again
    assert first != other


def test_per_failure_advances_on_report() -> None:
    pool = ProxyPool(["http://a:1", "http://b:1"], ProxyStrategy.PER_FAILURE)
    a = pool.pick()
    assert pool.pick() == a
    pool.report_failure()
    b = pool.pick()
    assert b != a


def test_from_file(tmp_path: Path) -> None:
    path = tmp_path / "proxies.txt"
    path.write_text(
        "# comment\nhttp://a:1\n\nhttp://b:2\n",
        encoding="utf-8",
    )
    pool = ProxyPool.from_file(path)
    assert len(pool) == 2
