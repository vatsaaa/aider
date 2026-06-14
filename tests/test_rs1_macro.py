"""Unit tests for the RS1 macro agent (agents/rs1_macro.py)."""

from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime, timezone, timedelta

import fakeredis
import pytest
from sqlalchemy import create_engine, text


REQUIRED_ENV = {
    "ANTHROPIC_API_KEY": "dummy",
    "AIDER_DATABASE_URL": "sqlite:///:memory:",
    "REDIS_URL": "redis://localhost:6379",
    "FRED_API_KEY": "dummy",
    "SEC_USER_AGENT": "Test User test@example.com",
}


def _reload_modules(monkeypatch, tmp_path):
    db_url = f"sqlite:///{tmp_path / 'rs1.db'}"
    monkeypatch.setenv("AIDER_DATABASE_URL", db_url)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
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


def _create_dlq_table(db_url: str) -> None:
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
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "regime TEXT NOT NULL, "
                "confidence REAL NOT NULL, "
                "sector_overweights TEXT NOT NULL, "
                "sector_underweights TEXT NOT NULL, "
                "reasoning TEXT, "
                "classified_at TEXT)"
            )
        )


def _build_message(busmod, payload: dict) -> object:
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


def test_rs1_publishes_m2_on_valid_trigger(monkeypatch, tmp_path):
    busmod, agentmod, db_url = _reload_modules(monkeypatch, tmp_path)
    _create_dlq_table(db_url)

    client = fakeredis.FakeRedis()
    bus = busmod.RedisStreamsBus(client, db_url=db_url)
    engine = create_engine(db_url)

    Agent = agentmod.RS1MacroAgent
    agent = Agent(bus=bus, db=engine, settings=importlib.import_module("core.config").settings)

    # Patch data sources and LLM
    monkeypatch.setattr(agent, "_get_fred_data", lambda: {"FEDFUNDS": 5.0})
    monkeypatch.setattr(agent, "_get_fomc_summary", lambda: "FOMC text")

    def fake_llm(*args, **kwargs):
        return {
            "regime": "hiking",
            "sector_overweights": ["Financials", "Energy", "Industrials"],
            "sector_underweights": ["Consumer Staples", "Healthcare", "Utilities"],
            "confidence": 0.9,
            "reasoning": "sample",
        }

    monkeypatch.setattr(agent, "call_llm", fake_llm)

    # Build a minimal M1 envelope
    payload = {
        "message_id": "m1",
        "pipeline_run_id": "run-1",
        "trigger_type": "manual",
        "ticker": "AAPL",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": {"ticker": "AAPL", "trigger_type": "manual", "pipeline_run_id": "run-1"},
        "metadata": {},
    }

    message = _build_message(busmod, payload)



    def test_rs1_uses_bus_cache_for_fred_data(monkeypatch, tmp_path):
        busmod, agentmod, db_url = _reload_modules(monkeypatch, tmp_path)
        _create_dlq_table(db_url)

        client = fakeredis.FakeRedis()
        bus = busmod.RedisStreamsBus(client, db_url=db_url)
        engine = create_engine(db_url)

        Agent = agentmod.RS1MacroAgent
        agent = Agent(bus=bus, db=engine, settings=importlib.import_module("core.config").settings)

        cached_payload = {"FEDFUNDS": 4.75, "DGS10": 4.2}
        bus.set_cache(agent.FRED_CACHE_KEY, json.dumps(cached_payload), ttl_seconds=60)

        def fail_if_called(*args, **kwargs):
            raise AssertionError("network fetch should not be used when cache is warm")

        monkeypatch.setattr(agent, "_get_fomc_summary", lambda: "FOMC text")
        monkeypatch.setattr(agent, "call_llm", fail_if_called)

        payload = {
            "message_id": "m-cache",
            "pipeline_run_id": "run-cache",
            "trigger_type": "manual",
            "ticker": "AAPL",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {"ticker": "AAPL", "trigger_type": "manual", "pipeline_run_id": "run-cache"},
            "metadata": {},
        }
        message = _build_message(busmod, payload)

        fred = agent._get_fred_data()
        assert fred == cached_payload
    m2 = agent.process(message)
    agent.publish_result(m2, message)

    assert client.xlen("stage:rs1:output") == 1
    entry = client.xrange("stage:rs1:output", count=1)[0][1]
    rendered = json.loads(entry[b"data"].decode())
    assert rendered["payload"]["regime"] == "hiking"


def test_rs1_routes_to_dlq_on_low_confidence(monkeypatch, tmp_path):
    busmod, agentmod, db_url = _reload_modules(monkeypatch, tmp_path)
    _create_dlq_table(db_url)

    client = fakeredis.FakeRedis()
    bus = busmod.RedisStreamsBus(client, db_url=db_url)
    engine = create_engine(db_url)

    Agent = agentmod.RS1MacroAgent
    agent = Agent(bus=bus, db=engine, settings=importlib.import_module("core.config").settings)

    monkeypatch.setattr(agent, "_get_fred_data", lambda: {"FEDFUNDS": 5.0})
    monkeypatch.setattr(agent, "_get_fomc_summary", lambda: "FOMC text")

    def low_conf_llm(*args, **kwargs):
        return {
            "regime": "easing",
            "sector_overweights": ["Consumer Staples", "Healthcare", "Utilities"],
            "sector_underweights": ["Financials", "Energy", "Industrials"],
            "confidence": 0.3,
            "reasoning": "low",
        }

    monkeypatch.setattr(agent, "call_llm", low_conf_llm)

    payload = {
        "message_id": "m2",
        "pipeline_run_id": "run-2",
        "trigger_type": "manual",
        "ticker": "MSFT",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": {"ticker": "MSFT", "trigger_type": "manual", "pipeline_run_id": "run-2"},
        "metadata": {},
    }

    message = _build_message(busmod, payload)

    with pytest.raises(Exception):
        try:
            agent.process(message)
        except Exception as err:
            # Simulate the run-time handling of a FatalError which publishes to DLQ
            if isinstance(err, agentmod.FatalError) or err.__class__.__name__ == "FatalError":
                agent._handle_fatal_error(message, err)
            raise

    assert client.xlen("dlq:failed") == 1


def test_rs1_uses_cached_regime_for_company_trigger(monkeypatch, tmp_path):
    busmod, agentmod, db_url = _reload_modules(monkeypatch, tmp_path)
    _create_dlq_table(db_url)

    client = fakeredis.FakeRedis()
    bus = busmod.RedisStreamsBus(client, db_url=db_url)
    engine = create_engine(db_url)

    Agent = agentmod.RS1MacroAgent
    agent = Agent(bus=bus, db=engine, settings=importlib.import_module("core.config").settings)

    # Seed a recent regime
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS macro_regime (id INTEGER PRIMARY KEY AUTOINCREMENT, regime TEXT, confidence REAL, sector_overweights TEXT, sector_underweights TEXT, reasoning TEXT, classified_at TEXT)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO macro_regime (regime, confidence, sector_overweights, sector_underweights, reasoning, classified_at) VALUES (:r, :c, :s, :u, :re, :at)"
            ),
            {
                "r": "recovery",
                "c": 0.88,
                "s": json.dumps(["tech"]),
                "u": json.dumps(["utilities"]),
                "re": "recent",
                "at": (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(),
            },
        )

    called = {"llm": False}

    def fail_if_called(*args, **kwargs):
        called["llm"] = True
        raise AssertionError("LLM should not be called for fresh cached regime")

    monkeypatch.setattr(agent, "call_llm", fail_if_called)

    payload = {
        "message_id": "m3",
        "pipeline_run_id": "run-3",
        "trigger_type": "manual",
        "ticker": "AAPL",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": {"ticker": "AAPL", "trigger_type": "manual", "pipeline_run_id": "run-3"},
        "metadata": {},
    }

    message = _build_message(busmod, payload)

    m2 = agent.process(message)
    assert m2.regime == "recovery"
    assert called["llm"] is False


def test_rs1_macro_trigger_always_calls_llm(monkeypatch, tmp_path):
    busmod, agentmod, db_url = _reload_modules(monkeypatch, tmp_path)
    _create_dlq_table(db_url)

    client = fakeredis.FakeRedis()
    bus = busmod.RedisStreamsBus(client, db_url=db_url)
    engine = create_engine(db_url)

    Agent = agentmod.RS1MacroAgent
    agent = Agent(bus=bus, db=engine, settings=importlib.import_module("core.config").settings)

    # Seed a recent regime
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS macro_regime (id INTEGER PRIMARY KEY AUTOINCREMENT, regime TEXT, confidence REAL, sector_overweights TEXT, sector_underweights TEXT, reasoning TEXT, classified_at TEXT)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO macro_regime (regime, confidence, sector_overweights, sector_underweights, reasoning, classified_at) VALUES (:r, :c, :s, :u, :re, :at)"
            ),
            {
                "r": "peak",
                "c": 0.9,
                "s": json.dumps(["energy"]),
                "u": json.dumps(["utilities"]),
                "re": "recent",
                "at": (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(),
            },
        )

    called = {"llm": False}

    def llm_called(*args, **kwargs):
        called["llm"] = True
        return {
            "regime": "peak",
            "sector_overweights": ["Energy", "Financials", "Healthcare"],
            "sector_underweights": ["Consumer Discretionary", "Industrials", "Information Technology"],
            "confidence": 0.95,
            "reasoning": "now macro",
        }

    monkeypatch.setattr(agent, "call_llm", llm_called)

    payload = {
        "message_id": "m4",
        "pipeline_run_id": "run-4",
        "trigger_type": "fred_release",
        "ticker": "__MACRO__",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": {"ticker": "__MACRO__", "trigger_type": "fred_release", "pipeline_run_id": "run-4"},
        "metadata": {},
    }

    message = _build_message(busmod, payload)

    m2 = agent.process(message)
    assert called["llm"] is True
    assert m2.regime == "peak"
