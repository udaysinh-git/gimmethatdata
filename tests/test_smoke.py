"""Smoke tests: package imports, CLI loads, settings parse."""

from __future__ import annotations

from typer.testing import CliRunner

from gimmethatdata import __version__
from gimmethatdata.cli import app
from gimmethatdata.config import Settings, load_settings


def test_version_string() -> None:
    assert __version__ == "0.1.0"


def test_cli_help_exits_zero() -> None:
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "gimmethatdata" in result.output


def test_cli_version_flag() -> None:
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_settings_defaults_load() -> None:
    settings = load_settings()
    assert isinstance(settings, Settings)
    assert settings.concurrency >= 1
    assert settings.fetch.timeout_seconds > 0
