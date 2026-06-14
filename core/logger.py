"""Structured logging configuration for the Digital Equity Analyst.

This module centralizes structlog setup so every service emits consistent JSON
log lines with the same correlation fields.
"""

from __future__ import annotations

from typing import Any

import structlog


def configure_logging() -> None:
    """Configure structlog for JSON output if it has not already been set up."""

    if getattr(configure_logging, "_configured", False):
        return

    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer(sort_keys=True),
        ],
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    configure_logging._configured = True  # type: ignore[attr-defined]


def get_logger(**context: Any):
    """Return a structlog logger bound to the given context."""

    configure_logging()
    return structlog.get_logger().bind(**context)


__all__ = ["configure_logging", "get_logger"]