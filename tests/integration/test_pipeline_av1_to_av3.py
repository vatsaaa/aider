"""Integration coverage for the AV1 to AV3 balance-check path."""

from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

import fakeredis
import pytest
from sqlalchemy import create_engine, text


def _reload_modules(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Reload the AV2 runtime against a dedicated SQLite database."""

    db_url = f"sqlite:///{tmp_path / 'av_pipeline.db'}"
    monkeypatch.setenv("AIDER_DATABASE_URL", db_url)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    monkeypatch.setenv("FRED_API_KEY", "dummy")
    monkeypatch.setenv("SEC_USER_AGENT", "Test User test@example.com")
    monkeypatch.setenv("ENV", "development")

    for name in ["agents.av2_model", "core.config", "models.financial_model", "core.bus"]:
        if name in sys.modules:
            del sys.modules[name]

    av2_model = importlib.import_module("agents.av2_model")
    busmod = importlib.import_module("core.bus")
    return av2_model, busmod, db_url


def _create_tables(db_url: str) -> None:
    """Create the minimal SQLite tables required for the AV2 integration test."""

    engine = create_engine(db_url, future=True)
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS pipeline_runs ("
                "run_id TEXT PRIMARY KEY, ticker TEXT, trigger_type TEXT, status TEXT, started_at TEXT, completed_at TEXT, git_commit_hash TEXT)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS data_packages ("
                "data_package_id TEXT PRIMARY KEY, run_id TEXT, ticker TEXT NOT NULL, fetched_at TEXT, payload TEXT NOT NULL, auditor_flags TEXT DEFAULT '[]')"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS financial_models ("
                "model_id TEXT PRIMARY KEY, run_id TEXT, ticker TEXT NOT NULL, built_at TEXT, wacc NUMERIC, scenarios TEXT NOT NULL, balance_ok INTEGER NOT NULL, payload TEXT NOT NULL, sensitivity_table TEXT)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS dlq_entries ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, stream TEXT NOT NULL, message_id TEXT, reason TEXT, payload TEXT, created_at TEXT)"
            )
        )


def _seed_unbalanced_data_package(db_url: str, data_package_id: str, run_id: str) -> None:
    """Insert a deliberately inconsistent data package row."""

    payload = {
        "ticker": "AAPL",
        "financials": {
            "historical_revenue": 1_000_000_000.0,
            "revenue_growth": [0.05, 0.04, 0.035, 0.03, 0.025],
            "cogs_pct_revenue": 0.54,
            "opex_pct_revenue": 0.18,
            "da_pct_revenue": 0.04,
            "tax_rate": 0.21,
            "interest_rate": 0.05,
            "debt": 250_000_000.0,
            "cash": 180_000_000.0,
            "current_assets_pct_revenue": 0.22,
            "current_liabilities_pct_revenue": 0.14,
            "net_ppe_pct_revenue": 0.35,
            "capex_pct_revenue": 0.06,
            "dividend_payout_pct": 0.20,
            "debt_amortization_pct": 0.03,
        },
        "market": {"beta": 1.15, "risk_free_rate": 0.045, "erp": 0.055},
        "opening_balance_sheet": {"assets": 1_000_000_000.0, "liabilities": 500_000_000.0, "equity": 400_000_000.0},
    }

    engine = create_engine(db_url, future=True)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO data_packages (data_package_id, run_id, ticker, fetched_at, payload, auditor_flags) "
                "VALUES (:data_package_id, :run_id, :ticker, CURRENT_TIMESTAMP, :payload, :auditor_flags)"
            ),
            {
                "data_package_id": data_package_id,
                "run_id": run_id,
                "ticker": "AAPL",
                "payload": json.dumps(payload),
                "auditor_flags": json.dumps([]),
            },
        )


def _build_message(busmod, *, data_package_id: str, run_id: str):
    """Construct the stage:av1:output message consumed by AV2."""

    payload = {"ticker": "AAPL", "data_package_id": data_package_id}
    envelope = {
        "message_id": "msg-1",
        "pipeline_run_id": run_id,
        "trigger_type": "manual",
        "ticker": "AAPL",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
        "metadata": {"retry_count": 0},
    }
    return busmod.Message(
        id="1",
        stream="stage:av1:output",
        data=envelope,
        pipeline_run_id=run_id,
        ticker="AAPL",
        trigger_type="manual",
        timestamp=datetime.now(timezone.utc).isoformat(),
        payload=payload,
        metadata={"retry_count": 0},
    )


def test_balance_check_fails_to_dlq(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """An unbalanced AV2 input should be routed to the DLQ by the agent loop."""

    av2_model, busmod, db_url = _reload_modules(monkeypatch, tmp_path)
    _create_tables(db_url)
    data_package_id = "dp-bad"
    run_id = "run-bad"
    _seed_unbalanced_data_package(db_url, data_package_id, run_id)

    bus = busmod.RedisStreamsBus(fakeredis.FakeRedis(), db_url=db_url)
    message = _build_message(busmod, data_package_id=data_package_id, run_id=run_id)
    bus.publish("stage:av1:output", message.data)

    real_consume = bus.consume
    calls = {"count": 0}

    def consume_once(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_consume(*args, **kwargs)
        raise StopIteration

    monkeypatch.setattr(bus, "consume", consume_once)

    agent = av2_model.AV2ModelAgent(bus=bus, db=create_engine(db_url), settings=SimpleNamespace(DATABASE_URL=db_url))
    agent.run()

    assert bus.get_stream_length("dlq:failed") == 1
    with create_engine(db_url).connect() as conn:
        row = conn.execute(text("SELECT reason FROM dlq_entries LIMIT 1")).fetchone()
    assert row[0] == "model_balance_failure"