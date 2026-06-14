"""Custom exceptions used across the Digital Equity Analyst pipeline.

This module centralizes domain-specific exceptions so agents, routers, and
infrastructure code can raise consistent error types without importing stage
implementations directly.
"""

from __future__ import annotations


class FatalError(Exception):
    """Raised when an agent encounters an unrecoverable error.

    Fatal errors are not retried. The owning agent should route the message to
    the DLQ and acknowledge the stream entry so it does not remain pending.

    Args:
        reason: Machine-readable failure reason.
        run_id: Optional pipeline run identifier associated with the failure.
    """

    def __init__(self, reason: str, run_id: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.run_id = run_id


class OllamaUnavailableError(Exception):
    """Raised when the Ollama endpoint cannot be reached."""


class SpendLimitError(Exception):
    """Raised when Claude spend is at or above the configured limit."""


__all__ = ["FatalError", "OllamaUnavailableError", "SpendLimitError"]