"""Tests for the RS2 Sector Agent (agents/rs2_sector.py)."""

from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime, timezone

import fakeredis
import pytest
from sqlalchemy import create_engine


def _reload_modules(monkeypatch, tmp_path):
    db_url = f"sqlite:///{tmp_path / 'rs2.db'}"
    monkeypatch.setenv("AIDER_DATABASE_URL", db_url)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    monkeypatch.setenv("FRED_API_KEY", "dummy")
    monkeypatch.setenv("SEC_USER_AGENT", "Test User test@example.com")
    monkeypatch.setenv("ENV", "development")

    for name in ["agents.rs2_sector", "core.config", "core"]:
        if name in sys.modules:
            del sys.modules[name]

    busmod = importlib.import_module("core.bus")
    agentmod = importlib.import_module("agents.rs2_sector")
    return busmod, agentmod, db_url


def _build_message(busmod, payload: dict) -> object:
    from core.bus import Message

    return Message(
        id="1",
        stream="stage:rs1:output",
        data=payload,
        pipeline_run_id=payload.get("pipeline_run_id"),
        ticker=payload.get("ticker"),
        trigger_type=payload.get("trigger_type"),
        timestamp=payload.get("timestamp"),
        payload=payload.get("payload", {}),
        metadata=payload.get("metadata", {}),
    )


def test_rs2_publishes_m3(monkeypatch, tmp_path):
    busmod, agentmod, db_url = _reload_modules(monkeypatch, tmp_path)
    client = fakeredis.FakeRedis()
    bus = busmod.RedisStreamsBus(client, db_url=db_url)
    engine = create_engine(db_url)

    Agent = agentmod.RS2SectorAgent
    agent = Agent(bus=bus, db=engine, settings=importlib.import_module("core.config").settings)

    # Mock LLM to return valid M3 structure
    def fake_llm(*args, **kwargs):
        return {
            "sector_scores": {
                "Information Technology": 0.8,
                "Financials": 0.6,
                "Healthcare": 0.5,
                "Consumer Discretionary": 0.4,
                "Consumer Staples": 0.3,
                "Industrials": 0.2,
                "Energy": 0.1,
            },
            "primary_sector": "Information Technology",
            "reasoning": "sample reasoning",
        }

    monkeypatch.setattr(agent, "call_llm", fake_llm)

    payload = {
        "message_id": "m1",
        "pipeline_run_id": "run-1",
        "trigger_type": "manual",
        "ticker": "__MACRO__",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": {
            "regime": "hiking",
            "sector_overweights": ["Financials"],
            "sector_underweights": ["Consumer Staples", "Healthcare", "Utilities"],
            "confidence": 0.9,
            "reasoning": "test",
        },
        "metadata": {},
    }

    message = _build_message(busmod, payload)

    m3 = agent.process(message)
    assert m3.primary_sector == "Information Technology"
    assert len(m3.sector_scores) == 7


def test_rs2_sector_scores_sum_to_reasonable_range(monkeypatch, tmp_path):
    busmod, agentmod, db_url = _reload_modules(monkeypatch, tmp_path)
    client = fakeredis.FakeRedis()
    bus = busmod.RedisStreamsBus(client, db_url=db_url)
    engine = create_engine(db_url)

    Agent = agentmod.RS2SectorAgent
    agent = Agent(bus=bus, db=engine, settings=importlib.import_module("core.config").settings)

    def fake_llm(*args, **kwargs):
        return {
            "sector_scores": {
                "Information Technology": 0.8,
                "Financials": 0.6,
                "Healthcare": 0.5,
                "Consumer Discretionary": 0.4,
                "Consumer Staples": 0.3,
                "Industrials": 0.2,
                "Energy": 0.1,
            },
            "primary_sector": "Information Technology",
            "reasoning": "sample reasoning",
        }

    monkeypatch.setattr(agent, "call_llm", fake_llm)

    payload = {
        "message_id": "m2",
        "pipeline_run_id": "run-2",
        "trigger_type": "manual",
        "ticker": "__MACRO__",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": {
            "regime": "easing",
            "sector_overweights": [],
            "sector_underweights": [],
            "confidence": 0.8,
            "reasoning": "test",
        },
        "metadata": {},
    }

    message = _build_message(busmod, payload)

    m3 = agent.process(message)
    for score in m3.sector_scores.values():
        assert 0.0 <= score <= 1.0
