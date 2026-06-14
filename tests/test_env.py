"""Tests for environment loading helpers."""

from __future__ import annotations

import os

from core.env import Env


def test_env_load_and_get(monkeypatch, tmp_path):
    # Create a temporary dotenv file
    dotenv = tmp_path / ".env.test"
    dotenv.write_text("TEST_KEY=hello\n")

    # Ensure key not set initially
    monkeypatch.delenv("TEST_KEY", raising=False)

    # Load the tempfile and verify
    Env.load(str(dotenv))
    assert Env.get("TEST_KEY") == "hello"

    # Non-existent key returns default
    assert Env.get("NOPE", default="x") == "x"
