"""Jinja2 prompt loading helpers for the LLM layer.

This module centralizes template rendering so prompt assembly stays consistent
across the agents and tests can exercise the exact prompt text before the
router ever sees it.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from jinja2 import Environment, FileSystemLoader


@lru_cache(maxsize=1)
def _environment() -> Environment:
    """Build the Jinja2 environment rooted at config/prompts."""

    return Environment(loader=FileSystemLoader("config/prompts"), autoescape=False)


def load_prompt(template_name: str, **context: Any) -> str:
    """Render a prompt template from config/prompts with the provided context."""

    template = _environment().get_template(template_name)
    return template.render(**context)