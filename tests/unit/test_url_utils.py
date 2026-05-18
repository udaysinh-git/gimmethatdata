"""Tests for core/url_utils."""

from __future__ import annotations

from pathlib import Path

import pytest

from gimmethatdata.core.url_utils import (
    absolute,
    canonicalize,
    derive_output_dir,
    domain_of,
    is_same_domain,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://Example.com/Path/#frag", "https://example.com/Path"),
        ("HTTPS://example.com/", "https://example.com/"),
        ("http://example.com/a/b/", "http://example.com/a/b"),
        ("https://example.com/?x=1#y", "https://example.com/?x=1"),
    ],
)
def test_canonicalize(raw: str, expected: str) -> None:
    assert canonicalize(raw) == expected


def test_absolute_resolves_relative_paths() -> None:
    assert absolute("https://example.com/a/b", "../c") == "https://example.com/c"
    assert absolute("https://example.com/", "//cdn.example.com/x.png") == "https://cdn.example.com/x.png"


def test_domain_of_strips_userinfo_and_case() -> None:
    assert domain_of("https://USER@Example.COM/foo") == "example.com"


def test_is_same_domain() -> None:
    assert is_same_domain("https://example.com/a", "https://example.com/b")
    assert not is_same_domain("https://example.com/", "https://other.com/")


def test_derive_output_dir_root_page() -> None:
    out = derive_output_dir(Path("out"), "https://example.com/")
    assert out == Path("out") / "example.com" / "_index"


def test_derive_output_dir_nested_path_and_query() -> None:
    out = derive_output_dir(Path("out"), "https://example.com/blog/post-1?utm=x")
    assert out.parts[:2] == ("out", "example.com")
    assert "blog" in out.name and "post-1" in out.name
