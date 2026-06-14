"""Tests for core.config settings validation and loading."""

from __future__ import annotations

import importlib
import sys

import pytest


REQUIRED = [
    "ANTHROPIC_API_KEY",
    "AIDER_DATABASE_URL",
    "REDIS_URL",
    "FRED_API_KEY",
    "SEC_USER_AGENT",
]


def _reload_config():
    """Reload core.config to force re-evaluation of module-level code."""
    import core.config
    return importlib.reload(core.config)


@pytest.mark.parametrize("missing_var", REQUIRED)
def test_settings_raises_on_missing_required_var(monkeypatch, missing_var):
    """Each required env var missing should cause import to raise EnvironmentError."""

    # Set all required vars to safe dummy values
    for v in REQUIRED:
        monkeypatch.setenv(v, "dummy")

    # Remove the var under test
    monkeypatch.delenv(missing_var, raising=False)

    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: None)

    with pytest.raises(EnvironmentError) as exc:
        _reload_config()

    assert missing_var in str(exc.value)


def test_settings_loads_with_all_required_vars(monkeypatch):
    """Providing all required vars should allow importing settings."""

    for v in REQUIRED:
        monkeypatch.setenv(v, "dummy")

    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: None)

    # Set a couple of optional vars to ensure parsing works
    monkeypatch.setenv("SMTP_PORT", "1025")
    monkeypatch.setenv("SMTP_TO", "a@x.com,b@y.com")

    mod = _reload_config()
    settings = mod.settings

    assert settings.ANTHROPIC_API_KEY == "dummy"
    assert settings.SMTP_PORT == 1025
    assert settings.SMTP_TO == ["a@x.com", "b@y.com"]
