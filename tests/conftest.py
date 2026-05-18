"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def blog_html() -> str:
    return (FIXTURES / "blog_post.html").read_text(encoding="utf-8")


@pytest.fixture
def doc_html() -> str:
    return (FIXTURES / "doc_page.html").read_text(encoding="utf-8")


@pytest.fixture
def landing_html() -> str:
    return (FIXTURES / "landing.html").read_text(encoding="utf-8")
