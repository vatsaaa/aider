"""Top-level core package for the Aider system.

This module intentionally avoids eager imports so that importing submodules
such as `core.schemas` does not force environment validation before tests or
callers have a chance to set required variables.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = ["settings"]


def __getattr__(name: str) -> Any:
	"""Lazily expose selected attributes from submodules."""

	if name == "settings":
		return import_module("core.config").settings
	raise AttributeError(name)
