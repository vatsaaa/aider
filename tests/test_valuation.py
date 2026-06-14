"""Tests for AV3 valuation helpers and agent behavior."""

from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime, timezone

from sqlalchemy import create_engine, text


def _reload(monkeypatch, tmp_path):
    """Reload valuation-related modules with deterministic environment variables."""

    db_url = f"sqlite:///{tmp_path / 'valuation.db'}"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setenv("AIDER_DATABASE_URL", db_url)
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    monkeypatch.setenv("FRED_API_KEY", "dummy")
    monkeypatch.setenv("SEC_USER_AGENT", "Test User test@example.com")
    monkeypatch.setenv("ENV", "development")

    for name in ["models.valuation", "agents.av3_valuation", "core.config", "core"]:
        if name in sys.modules:
            del sys.modules[name]

    core_valuation = importlib.import_module("models.valuation")
    av3_model = importlib.import_module("agents.av3_valuation")
    busmod = importlib.import_module("core.bus")
    config = importlib.import_module("core.config")
    return core_valuation, av3_model, busmod, config, db_url


def _create_tables(db_url: str) -> None:
    """Create the minimal SQLite tables required for AV3 tests."""

    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE IF NOT EXISTS pipeline_runs (run_id TEXT PRIMARY KEY, ticker TEXT, trigger_type TEXT, status TEXT, started_at TEXT, completed_at TEXT, git_commit_hash TEXT)")
        )
        conn.execute(
            text("CREATE TABLE IF NOT EXISTS data_packages (data_package_id TEXT PRIMARY KEY, run_id TEXT, ticker TEXT NOT NULL, fetched_at TEXT, payload TEXT NOT NULL, auditor_flags TEXT DEFAULT '[]')")
        )
        conn.execute(
            text("CREATE TABLE IF NOT EXISTS financial_models (model_id TEXT PRIMARY KEY, run_id TEXT, ticker TEXT NOT NULL, built_at TEXT, wacc NUMERIC, scenarios TEXT NOT NULL, balance_ok INTEGER NOT NULL, payload TEXT NOT NULL, sensitivity_table TEXT)")
        )
        conn.execute(
            text("CREATE TABLE IF NOT EXISTS coverage_universe (id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT UNIQUE, added_at TEXT, notes TEXT)")
        )


def _seed_data(db_url: str, *, run_id: str = "run-1", model_id: str = "model-1") -> None:
    """Insert a deterministic model row, data package, and coverage rows."""

    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO pipeline_runs (run_id, ticker, trigger_type, status) VALUES (:run_id, :ticker, 'manual', 'done')"), {"run_id": run_id, "ticker": "JPM"})
        data_package = {
            "ticker": "JPM",
            "financials": {"historical_revenue": 10_000_000.0, "debt": 500_000.0, "cash": 100_000.0},
            "market": {"shares_outstanding": 1_000_000.0, "market_cap": 1_200_000.0, "current_price": 1.2},
            "opening_balance_sheet": {"equity": 800_000.0},
        }
        conn.execute(
            text("INSERT INTO data_packages (data_package_id, run_id, ticker, fetched_at, payload, auditor_flags) VALUES (:id, :run_id, :ticker, CURRENT_TIMESTAMP, :payload, :auditor_flags)"),
            {"id": "dp-1", "run_id": run_id, "ticker": "JPM", "payload": json.dumps(data_package), "auditor_flags": json.dumps([])},
        )
        model_payload = {
            "income_statement": {"FY1": {"EBITDA": 200_000.0}, "FY2": {"EBITDA": 210_000.0}, "FY3": {"EBITDA": 220_000.0}, "FY4": {"EBITDA": 230_000.0}, "FY5": {"EBITDA": 240_000.0}},
            "cash_flow_statement": {},
            "balance_sheet": {},
        }
        conn.execute(
            text("INSERT INTO financial_models (model_id, run_id, ticker, built_at, wacc, scenarios, balance_ok, payload) VALUES (:model_id, :run_id, :ticker, CURRENT_TIMESTAMP, :wacc, :scenarios, 1, :payload)"),
            {
                "model_id": model_id,
                "run_id": run_id,
                "ticker": "JPM",
                "wacc": 0.10,
                "scenarios": json.dumps({"base": {"fcf": [100, 110, 120, 130, 140], "ebitda_margin": [0.2] * 5, "capex": [10] * 5, "exit_multiple": 12.0}}),
                "payload": json.dumps(model_payload),
            },
        )
        conn.execute(text("INSERT INTO coverage_universe (ticker, notes) VALUES (:ticker, :notes)"), {"ticker": "JPM", "notes": json.dumps({"sector": "Banking", "peers": ["BAC", "WFC"]})})
        conn.execute(text("INSERT INTO coverage_universe (ticker, notes) VALUES (:ticker, :notes)"), {"ticker": "BAC", "notes": json.dumps({"sector": "Banking"})})
        conn.execute(text("INSERT INTO coverage_universe (ticker, notes) VALUES (:ticker, :notes)"), {"ticker": "WFC", "notes": json.dumps({"sector": "Banking"})})


def _build_message(busmod, *, run_id: str = "run-1", model_id: str = "model-1"):
    """Construct a stage:av2:output message for AV3."""

    payload = {
        "model_id": model_id,
        "wacc": 0.10,
        "scenarios": {
            "base": {"fcf": [100.0, 110.0, 120.0, 130.0, 140.0], "ebitda_margin": [0.2] * 5, "capex": [10.0] * 5, "exit_multiple": 12.0},
            "bear": {"fcf": [90.0, 95.0, 100.0, 105.0, 110.0], "ebitda_margin": [0.18] * 5, "capex": [11.0] * 5, "exit_multiple": 10.0},
            "bull": {"fcf": [110.0, 120.0, 130.0, 140.0, 150.0], "ebitda_margin": [0.22] * 5, "capex": [9.0] * 5, "exit_multiple": 14.0},
        },
        "balance_ok": True,
    }
    return busmod.Message(
        id="1",
        stream="stage:av2:output",
        data={
            "message_id": "msg-1",
            "pipeline_run_id": run_id,
            "trigger_type": "manual",
            "ticker": "JPM",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
            "metadata": {"retry_count": 0},
        },
        pipeline_run_id=run_id,
        ticker="JPM",
        trigger_type="manual",
        timestamp=datetime.now(timezone.utc).isoformat(),
        payload=payload,
        metadata={"retry_count": 0},
    )


def test_dcf_terminal_value_is_60_to_80_pct_of_total(monkeypatch, tmp_path):
    """Terminal value should dominate but not overwhelm a normal DCF."""

    core_valuation, _, _, _, _ = _reload(monkeypatch, tmp_path)
    result = core_valuation.compute_dcf([100.0, 110.0, 120.0, 130.0, 140.0], 0.10)

    assert 0.60 <= result["terminal_value_share"] <= 0.80


def test_sensitivity_table_is_4x4(monkeypatch, tmp_path):
    """The sensitivity table must contain four WACC rows and four growth columns."""

    core_valuation, av3_model, busmod, config, db_url = _reload(monkeypatch, tmp_path)
    _create_tables(db_url)
    _seed_data(db_url)

    table = core_valuation.build_sensitivity_table([100.0, 110.0, 120.0, 130.0, 140.0])
    assert len(table) == 4
    for row in table.values():
        assert len(row) == 4
        assert all(value is not None for value in row.values())

    agent = av3_model.AV3ValuationAgent(bus=busmod.InMemoryBus(), db=create_engine(db_url), settings=config.settings)
    monkeypatch.setattr(agent, "call_llm", lambda **kwargs: {"reasoning": "A. B. C."})
    output = agent.process(_build_message(busmod))

    assert output.reasoning
    with create_engine(db_url).connect() as conn:
        row = conn.execute(text("SELECT sensitivity_table FROM financial_models WHERE model_id = 'model-1'" )).fetchone()
    stored = json.loads(row[0])
    assert len(stored) == 4
    assert all(len(values) == 4 for values in stored.values())


def test_rating_buy_when_upside_exceeds_hurdle(monkeypatch, tmp_path):
    """A 20% upside should produce a BUY rating."""

    core_valuation, _, _, _, _ = _reload(monkeypatch, tmp_path)
    assert core_valuation.derive_rating(100.0, 120.0) == "BUY"


def test_rating_sell_when_downside_exceeds_hurdle(monkeypatch, tmp_path):
    """A 20% downside should produce a SELL rating."""

    core_valuation, _, _, _, _ = _reload(monkeypatch, tmp_path)
    assert core_valuation.derive_rating(100.0, 80.0) == "SELL"


def test_peer_multiple_uses_sector_appropriate_metric(monkeypatch, tmp_path):
    """Banking names should use price-to-book rather than EV/EBITDA."""

    core_valuation, _, _, _, db_url = _reload(monkeypatch, tmp_path)
    _create_tables(db_url)
    _seed_data(db_url)

    class DummyTicker:
        def __init__(self, ticker):
            self.info = {
                "priceToBook": 1.5 if ticker == "BAC" else 1.2,
                "enterpriseToEbitda": 8.0,
                "forwardPE": 9.0,
            }

    monkeypatch.setattr("yfinance.Ticker", lambda ticker: DummyTicker(ticker))

    result = core_valuation.compute_peer_multiple(
        "JPM",
        {"book_value_per_share": 50.0, "ebitda": 200.0, "earnings_per_share": 5.0},
        create_engine(db_url),
    )

    assert result["metric_used"] == "P/B"
    assert result["median_multiple"] > 0
    assert result["implied_value"] > 0