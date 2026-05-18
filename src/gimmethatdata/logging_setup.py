"""Structured logging through structlog, rendered to a Rich console."""

from __future__ import annotations

import logging
import sys

import structlog
from rich.console import Console
from rich.logging import RichHandler

_STDLIB_CONFIGURED = False


def configure_logging(level: str = "INFO", *, force: bool = False) -> None:
    """Configure stdlib + structlog with Rich output. Safe to call repeatedly."""
    global _STDLIB_CONFIGURED
    if not _STDLIB_CONFIGURED or force:
        console = Console(stderr=True)
        handler = RichHandler(
            console=console,
            show_time=True,
            show_path=False,
            rich_tracebacks=True,
            markup=True,
        )
        logging.basicConfig(
            level=level.upper(),
            format="%(message)s",
            datefmt="[%X]",
            handlers=[handler],
            force=True,
        )
        _STDLIB_CONFIGURED = True
    else:
        logging.getLogger().setLevel(level.upper())

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty()),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger."""
    return structlog.get_logger(name)  # type: ignore[no-any-return]
