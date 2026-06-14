"""Tests for the shared structured logging configuration."""

from __future__ import annotations

import json

from core.logger import configure_logging, get_logger


def test_configure_logging_emits_json(capsys):
    """The shared logger should emit JSON with the configured context fields."""

    configure_logging()
    get_logger(agent_name="rs1_macro").info(
        "agent_event",
        run_id="run-1",
        ticker="AAPL",
        stream="trigger:events",
        duration_ms=12,
    )

    record = json.loads(capsys.readouterr().out.strip())
    assert record["event"] == "agent_event"
    assert record["agent_name"] == "rs1_macro"
    assert record["run_id"] == "run-1"
    assert record["ticker"] == "AAPL"
    assert record["stream"] == "trigger:events"
    assert record["duration_ms"] == 12
    assert record["timestamp"]
    assert record["level"] == "info"
