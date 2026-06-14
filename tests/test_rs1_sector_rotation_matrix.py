from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime, timezone

import fakeredis
import pytest
from sqlalchemy import create_engine, text


def _reload_modules(monkeypatch, tmp_path):
    db_url = f"sqlite:///{tmp_path / 'rs1_matrix.db'}"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setenv("AIDER_DATABASE_URL", db_url)
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    monkeypatch.setenv("FRED_API_KEY", "dummy")
    monkeypatch.setenv("SEC_USER_AGENT", "Test User test@example.com")
    monkeypatch.setenv("ENV", "development")

    for name in ["agents.rs1_macro", "core.config", "core"]:
        if name in sys.modules:
            del sys.modules[name]

    busmod = importlib.import_module("core.bus")
    agentmod = importlib.import_module("agents.rs1_macro")
    return busmod, agentmod, db_url


def _create_tables(db_url: str) -> None:
    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS dlq_entries ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, stream TEXT NOT NULL, message_id TEXT, reason TEXT, payload TEXT, created_at TEXT)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS macro_regime ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, regime TEXT NOT NULL, confidence REAL NOT NULL, sector_overweights TEXT NOT NULL, sector_underweights TEXT NOT NULL, reasoning TEXT, classified_at TEXT)"
            )
        )


def _message(busmod, payload: dict):
    from core.bus import Message

    return Message(
        id="1",
        stream="trigger:events",
        data=payload,
        pipeline_run_id=payload.get("pipeline_run_id"),
        ticker=payload.get("ticker"),
        trigger_type=payload.get("trigger_type"),
        timestamp=payload.get("timestamp"),
        payload=payload.get("payload", {}),
        metadata=payload.get("metadata", {}),
    )


def test_rs1_prompt_includes_sector_rotation_matrix(monkeypatch, tmp_path):
    busmod, agentmod, db_url = _reload_modules(monkeypatch, tmp_path)
    _create_tables(db_url)

    client = fakeredis.FakeRedis()
    bus = busmod.RedisStreamsBus(client, db_url=db_url)
    engine = create_engine(db_url)
    settings = importlib.import_module("core.config").settings
    agent = agentmod.RS1MacroAgent(bus=bus, db=engine, settings=settings)

    monkeypatch.setattr(agent, "_get_fred_data", lambda: {"FEDFUNDS": 5.0})
    monkeypatch.setattr(agent, "_get_fomc_summary", lambda: "FOMC text")

    captured = {}

    def fake_llm(*, system_prompt, user_prompt, response_schema, max_tokens):
        captured["system_prompt"] = system_prompt
        captured["user_prompt"] = user_prompt
        return {
            "regime": "hiking",
            "sector_overweights": ["Financials", "Energy", "Industrials"],
            "sector_underweights": ["Consumer Staples", "Healthcare", "Utilities"],
            "confidence": 0.9,
            "reasoning": "matrix-based",
        }

    monkeypatch.setattr(agent, "call_llm", fake_llm)

    payload = {
        "message_id": "m1",
        "pipeline_run_id": "run-matrix",
        "trigger_type": "manual",
        "ticker": "AAPL",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": {"ticker": "AAPL", "trigger_type": "manual", "pipeline_run_id": "run-matrix"},
        "metadata": {},
    }

    message = _message(busmod, payload)
    result = agent.process(message)

    assert result.regime == "hiking"
    assert "Sector rotation matrix:" in captured["user_prompt"]
    assert "Financials" in captured["user_prompt"]
    assert "Energy" in captured["user_prompt"]
    assert "overweights" in captured["user_prompt"]
    assert "underweights" in captured["user_prompt"]
    assert "matrix-based" == result.reasoning
    assert json.loads(json.dumps(result.model_dump()))["sector_overweights"] == ["Financials", "Energy", "Industrials"]


def test_rs1_rejects_sector_rotation_mismatch(monkeypatch, tmp_path):
    busmod, agentmod, db_url = _reload_modules(monkeypatch, tmp_path)
    _create_tables(db_url)

    client = fakeredis.FakeRedis()
    bus = busmod.RedisStreamsBus(client, db_url=db_url)
    engine = create_engine(db_url)
    settings = importlib.import_module("core.config").settings
    agent = agentmod.RS1MacroAgent(bus=bus, db=engine, settings=settings)

    monkeypatch.setattr(agent, "_get_fred_data", lambda: {"FEDFUNDS": 5.0})
    monkeypatch.setattr(agent, "_get_fomc_summary", lambda: "FOMC text")
    monkeypatch.setattr(
        agent,
        "call_llm",
        lambda **kwargs: {
            "regime": "hiking",
            "sector_overweights": ["Financials", "Energy", "Industrials"],
            "sector_underweights": ["Financials"],
            "confidence": 0.9,
            "reasoning": "mismatch",
        },
    )

    payload = {
        "message_id": "m2",
        "pipeline_run_id": "run-mismatch",
        "trigger_type": "manual",
        "ticker": "AAPL",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": {"ticker": "AAPL", "trigger_type": "manual", "pipeline_run_id": "run-mismatch"},
        "metadata": {},
    }

    message = _message(busmod, payload)

    with pytest.raises(agentmod.FatalError, match="rs1_sector_rotation_mismatch_underweights"):
        agent.process(message)
