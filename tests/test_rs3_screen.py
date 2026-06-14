"""Tests for the RS3 Screen Agent (agents/rs3_screen.py)."""

from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime, timezone

import fakeredis
import pytest
from sqlalchemy import create_engine, text


def _reload(monkeypatch, tmp_path):
    db_url = f"sqlite:///{tmp_path / 'rs3.db'}"
    monkeypatch.setenv("AIDER_DATABASE_URL", db_url)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    monkeypatch.setenv("FRED_API_KEY", "dummy")
    monkeypatch.setenv("SEC_USER_AGENT", "Test User test@example.com")
    monkeypatch.setenv("ENV", "development")

    for name in ["agents.rs3_screen", "core.config", "core"]:
        if name in sys.modules:
            del sys.modules[name]

    busmod = importlib.import_module("core.bus")
    agentmod = importlib.import_module("agents.rs3_screen")
    return busmod, agentmod, db_url


def _build_message(busmod, payload: dict) -> object:
    from core.bus import Message

    return Message(
        id="1",
        stream="stage:rs2:output",
        data=payload,
        pipeline_run_id=payload.get("pipeline_run_id"),
        ticker=payload.get("ticker"),
        trigger_type=payload.get("trigger_type"),
        timestamp=payload.get("timestamp"),
        payload=payload.get("payload", {}),
        metadata=payload.get("metadata", {}),
    )


def test_rs3_publishes_m4_with_candidates(monkeypatch, tmp_path):
    busmod, agentmod, db_url = _reload(monkeypatch, tmp_path)
    client = fakeredis.FakeRedis()
    bus = busmod.RedisStreamsBus(client, db_url=db_url)
    engine = create_engine(db_url)

    # Create minimal pipeline_runs and coverage_universe
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS pipeline_runs (run_id TEXT PRIMARY KEY, ticker TEXT)"))
        conn.execute(text("INSERT INTO pipeline_runs (run_id, ticker) VALUES (:r, :t)"), {"r": "run-1", "t": "ORIG"})
        conn.execute(text("CREATE TABLE IF NOT EXISTS coverage_universe (id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT, added_at TEXT, notes TEXT)"))
        # Two candidate tickers tagged with sector
        conn.execute(text("INSERT INTO coverage_universe (ticker, notes) VALUES (:tk, :notes)"), {"tk": "AAA", "notes": json.dumps({"sector": "Banking"})})
        conn.execute(text("INSERT INTO coverage_universe (ticker, notes) VALUES (:tk, :notes)"), {"tk": "BBB", "notes": json.dumps({"sector": "Banking"})})

    Agent = agentmod.RS3ScreenAgent
    agent = Agent(bus=bus, db=engine, settings=importlib.import_module("core.config").settings)

    # Mock yfinance.download to return dict of metrics
    def fake_download(tickers, **kwargs):
        return {
            "AAA": {"pe_ratio": 10, "ev_to_ebitda": 5, "pb": 1.2, "revenue_growth_yoy": 0.1, "gross_margin": 0.2, "net_debt_to_ebitda": 1.0},
            "BBB": {"pe_ratio": 20, "ev_to_ebitda": 10, "pb": 2.5, "revenue_growth_yoy": 0.05, "gross_margin": 0.15, "net_debt_to_ebitda": 2.0},
        }

    monkeypatch.setattr("yfinance.download", fake_download)

    # Mock LLM to return M4-like payload
    def fake_llm(*args, **kwargs):
        return {"candidates": [{"ticker": "AAA", "rationale": "cheap relative"}]}

    # Build message with M3 payload
    payload = {
        "message_id": "m1",
        "pipeline_run_id": "run-1",
        "trigger_type": "manual",
        "ticker": "ORIG",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": {"sector_scores": {}, "primary_sector": "Banking", "reasoning": "test"},
        "metadata": {},
    }

    monkeypatch.setattr(agent, "call_llm", fake_llm)

    message = _build_message(busmod, payload)
    m4 = agent.process(message)

    assert 1 <= len(m4.candidates) <= 5
    assert m4.candidates[0].ticker == "AAA"
    assert m4.candidates[0].rationale


def test_rs3_only_screens_correct_sector(monkeypatch, tmp_path):
    busmod, agentmod, db_url = _reload(monkeypatch, tmp_path)
    client = fakeredis.FakeRedis()
    bus = busmod.RedisStreamsBus(client, db_url=db_url)
    engine = create_engine(db_url)

    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS pipeline_runs (run_id TEXT PRIMARY KEY, ticker TEXT)"))
        conn.execute(text("INSERT INTO pipeline_runs (run_id, ticker) VALUES (:r, :t)"), {"r": "run-2", "t": "ORIG"})
        conn.execute(text("CREATE TABLE IF NOT EXISTS coverage_universe (id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT, added_at TEXT, notes TEXT)"))
        conn.execute(text("INSERT INTO coverage_universe (ticker, notes) VALUES (:tk, :notes)"), {"tk": "BANK1", "notes": json.dumps({"sector": "Banking"})})
        conn.execute(text("INSERT INTO coverage_universe (ticker, notes) VALUES (:tk, :notes)"), {"tk": "TECH1", "notes": json.dumps({"sector": "Information Technology"})})

    Agent = agentmod.RS3ScreenAgent
    agent = Agent(bus=bus, db=engine, settings=importlib.import_module("core.config").settings)

    called = {"tickers": None}

    def fake_download(tickers, **kwargs):
        called["tickers"] = tickers
        return {"BANK1": {"pe_ratio": 12}}

    monkeypatch.setattr("yfinance.download", fake_download)

    def fake_llm(*args, **kwargs):
        return {"candidates": [{"ticker": "BANK1", "rationale": "ok"}]}

    monkeypatch.setattr(agent, "call_llm", fake_llm)

    payload = {
        "message_id": "m2",
        "pipeline_run_id": "run-2",
        "trigger_type": "manual",
        "ticker": "ORIG",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": {"sector_scores": {}, "primary_sector": "Banking", "reasoning": "test"},
        "metadata": {},
    }

    message = _build_message(busmod, payload)
    m4 = agent.process(message)
    assert called["tickers"] is not None
    assert "TECH1" not in called["tickers"]


def test_rs3_handles_yfinance_failure_gracefully(monkeypatch, tmp_path):
    busmod, agentmod, db_url = _reload(monkeypatch, tmp_path)
    client = fakeredis.FakeRedis()
    bus = busmod.RedisStreamsBus(client, db_url=db_url)
    engine = create_engine(db_url)

    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS pipeline_runs (run_id TEXT PRIMARY KEY, ticker TEXT)"))
        conn.execute(text("INSERT INTO pipeline_runs (run_id, ticker) VALUES (:r, :t)"), {"r": "run-3", "t": "ORIG"})
        conn.execute(text("CREATE TABLE IF NOT EXISTS coverage_universe (id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT, added_at TEXT, notes TEXT)"))
        conn.execute(text("INSERT INTO coverage_universe (ticker, notes) VALUES (:tk, :notes)"), {"tk": "GOOD", "notes": json.dumps({"sector": "Banking"})})
        conn.execute(text("INSERT INTO coverage_universe (ticker, notes) VALUES (:tk, :notes)"), {"tk": "BAD", "notes": json.dumps({"sector": "Banking"})})

    Agent = agentmod.RS3ScreenAgent
    agent = Agent(bus=bus, db=engine, settings=importlib.import_module("core.config").settings)

    def fake_download(tickers, **kwargs):
        # Simulate failure when BAD is present
        if "BAD" in tickers:
            raise RuntimeError("yfinance hiccup")
        return {"GOOD": {"pe_ratio": 10}}

    monkeypatch.setattr("yfinance.download", fake_download)

    # Fallback per-ticker will be used; mock yf.Ticker.info if needed by agent fallback
    class DummyTicker:
        def __init__(self, t):
            self.info = {"trailingPE": 11}

    monkeypatch.setattr("yfinance.Ticker", lambda t: DummyTicker(t))

    def fake_llm(*args, **kwargs):
        return {"candidates": [{"ticker": "GOOD", "rationale": "ok"}]}

    monkeypatch.setattr(agent, "call_llm", fake_llm)

    payload = {
        "message_id": "m3",
        "pipeline_run_id": "run-3",
        "trigger_type": "manual",
        "ticker": "ORIG",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": {"sector_scores": {}, "primary_sector": "Banking", "reasoning": "test"},
        "metadata": {},
    }

    message = _build_message(busmod, payload)
    m4 = agent.process(message)
    # Ensure GOOD made it through
    assert any(c.ticker == "GOOD" for c in m4.candidates)
