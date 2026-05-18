"""Pipe structlog output into the TUI instead of stderr.

Swaps structlog's PrintLoggerFactory for an in-memory sink that the progress
screen drains on a tick.
"""

from __future__ import annotations

import logging
from collections import deque

import structlog


class TUILogSink:
    """File-like sink — `write(str)` lands in an internal deque the TUI drains."""

    def __init__(self, max_buffer: int = 2000) -> None:
        self._buffer: deque[str] = deque(maxlen=max_buffer)

    def write(self, msg: str) -> int:
        text = msg.rstrip("\n")
        if text:
            self._buffer.append(text)
        return len(msg)

    def flush(self) -> None:
        return None

    def pop_all(self) -> list[str]:
        """Return and clear all buffered lines."""
        if not self._buffer:
            return []
        lines = list(self._buffer)
        self._buffer.clear()
        return lines

    def __len__(self) -> int:
        return len(self._buffer)


class _LoggingCapture:
    """Save + restore the structlog default config."""

    def __init__(self) -> None:
        self._installed = False

    def install(self, sink: TUILogSink, *, level: str = "INFO") -> None:
        structlog.reset_defaults()
        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.processors.add_log_level,
                structlog.processors.TimeStamper(fmt="%H:%M:%S", utc=False),
                structlog.dev.ConsoleRenderer(colors=False),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(
                getattr(logging, level.upper(), logging.INFO)
            ),
            context_class=dict,
            logger_factory=structlog.PrintLoggerFactory(file=sink),  # type: ignore[arg-type]
            cache_logger_on_first_use=False,
        )
        self._installed = True

    def restore(self) -> None:
        if not self._installed:
            return
        structlog.reset_defaults()
        # Re-apply the default human console renderer to stderr.
        from gimmethatdata.logging_setup import configure_logging

        configure_logging(level="INFO")
        self._installed = False


_capture = _LoggingCapture()


def install(sink: TUILogSink, *, level: str = "INFO") -> None:
    """Route structlog output to `sink`."""
    _capture.install(sink, level=level)


def restore() -> None:
    """Restore the default stderr-bound structlog config."""
    _capture.restore()
