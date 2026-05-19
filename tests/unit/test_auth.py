"""Tests for fetch/auth."""

from __future__ import annotations

from pathlib import Path

import pytest

from gimmethatdata.fetch.auth import AuthConfig, parse_cookies_file


def test_basic_auth_encoded() -> None:
    cfg = AuthConfig.from_cli(auth="basic:alice:s3cret", cookies_arg=None, cookies_file=None, headers_arg=None)
    headers = cfg.header_overrides()
    assert headers["Authorization"] == "Basic YWxpY2U6czNjcmV0"


def test_bearer_token() -> None:
    cfg = AuthConfig.from_cli(auth="bearer:abc.xyz", cookies_arg=None, cookies_file=None, headers_arg=None)
    assert cfg.header_overrides()["Authorization"] == "Bearer abc.xyz"


def test_cookies_inline_and_extra_headers() -> None:
    cfg = AuthConfig.from_cli(
        auth=None,
        cookies_arg=["sid=abc", "remember=1; theme=dark"],
        cookies_file=None,
        headers_arg=["X-Foo: bar", "User-Agent: custom-ua"],
    )
    headers = cfg.header_overrides()
    assert "sid=abc" in headers["Cookie"]
    assert "remember=1" in headers["Cookie"]
    assert "theme=dark" in headers["Cookie"]
    assert headers["X-Foo"] == "bar"
    assert headers["User-Agent"] == "custom-ua"


def test_invalid_auth_scheme() -> None:
    with pytest.raises(ValueError, match="basic"):
        AuthConfig.from_cli(auth="oauth:xx", cookies_arg=None, cookies_file=None, headers_arg=None)


def test_invalid_header_format() -> None:
    with pytest.raises(ValueError, match="--header"):
        AuthConfig.from_cli(auth=None, cookies_arg=None, cookies_file=None, headers_arg=["nope"])


def test_netscape_cookies_file(tmp_path: Path) -> None:
    path = tmp_path / "cookies.txt"
    path.write_text(
        "# Netscape HTTP Cookie File\n"
        ".example.com\tTRUE\t/\tFALSE\t0\tsession\tabc123\n"
        ".example.com\tTRUE\t/\tFALSE\t0\ttheme\tdark\n",
        encoding="utf-8",
    )
    cookies = parse_cookies_file(path)
    assert cookies == {"session": "abc123", "theme": "dark"}
