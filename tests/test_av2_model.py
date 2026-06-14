"""Tests for the AV2 three-statement financial model and agent."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import fakeredis
import pytest
import yaml
from sqlalchemy import create_engine, text


def _reload_modules(monkeypatch, tmp_path):
    """Reload AV2-related modules with deterministic environment variables."""

    db_url = f"sqlite:///{tmp_path / 'av2.db'}"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setenv("AIDER_DATABASE_URL", db_url)
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    monkeypatch.setenv("FRED_API_KEY", "dummy")
    monkeypatch.setenv("SEC_USER_AGENT", "Test User test@example.com")
    monkeypatch.setenv("ENV", "development")

    for name in ["models.financial_model", "agents.av2_model", "core.config", "core.exceptions", "core"]:
        if name in sys.modules:
            del sys.modules[name]

    financial_model = importlib.import_module("models.financial_model")
    av2_model = importlib.import_module("agents.av2_model")
    busmod = importlib.import_module("core.bus")
    config = importlib.import_module("core.config")
    return financial_model, av2_model, busmod, config, db_url


def _create_tables(db_url: str) -> None:
    """Create the minimal SQLite tables required for AV2 tests."""

    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS data_packages ("
                "data_package_id TEXT PRIMARY KEY, run_id TEXT, ticker TEXT NOT NULL, fetched_at TEXT, payload TEXT NOT NULL, auditor_flags TEXT DEFAULT '[]')"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS financial_models ("
                "model_id TEXT PRIMARY KEY, run_id TEXT, ticker TEXT NOT NULL, built_at TEXT, wacc NUMERIC, scenarios TEXT NOT NULL, balance_ok INTEGER NOT NULL, payload TEXT NOT NULL)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS dlq_entries ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, stream TEXT NOT NULL, message_id TEXT, reason TEXT, payload TEXT, created_at TEXT)"
            )
        )


def _sample_data_package(balance_ok: bool = True) -> dict[str, object]:
    """Return a compact data package with deterministic financial assumptions."""

    if balance_ok:
        opening_assets = 1_050_000_000.0
        opening_liabilities = 420_000_000.0
        opening_equity = 630_000_000.0
    else:
        opening_assets = 1_000_000_000.0
        opening_liabilities = 500_000_000.0
        opening_equity = 400_000_000.0

    return {
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
        "opening_balance_sheet": {
            "assets": opening_assets,
            "liabilities": opening_liabilities,
            "equity": opening_equity,
        },
    }


def _seed_data_package(db_url: str, data_package_id: str, payload: dict[str, object]) -> None:
    """Insert a sample data package row into the SQLite test database."""

    with create_engine(db_url).begin() as conn:
        conn.execute(
            text(
                "INSERT INTO data_packages (data_package_id, run_id, ticker, fetched_at, payload, auditor_flags) "
                "VALUES (:data_package_id, :run_id, :ticker, CURRENT_TIMESTAMP, :payload, :auditor_flags)"
            ),
            {
                "data_package_id": data_package_id,
                "run_id": "run-1",
                "ticker": "AAPL",
                "payload": json.dumps(payload),
                "auditor_flags": json.dumps([]),
            },
        )


def _build_message(busmod, data_package_id: str, run_id: str = "run-1"):
    """Construct an input message envelope for the AV2 agent."""

    return busmod.Message(
        id="1",
        stream="stage:av1:output",
        data={
            "message_id": "msg-1",
            "pipeline_run_id": run_id,
            "trigger_type": "manual",
            "ticker": "AAPL",
            "timestamp": "2026-05-22T00:00:00Z",
            "payload": {"data_package_id": data_package_id, "ticker": "AAPL"},
            "metadata": {"retry_count": 0},
        },
        pipeline_run_id=run_id,
        ticker="AAPL",
        trigger_type="manual",
        timestamp="2026-05-22T00:00:00Z",
        payload={"ticker": "AAPL", "data_package_id": data_package_id},
        metadata={"retry_count": 0},
    )


def test_three_statement_model_balances(monkeypatch, tmp_path):
    """A synthetic balanced data package should produce a balanced model."""

    financial_model, _, _, _, _ = _reload_modules(monkeypatch, tmp_path)
    model = financial_model.ThreeStatementModel(_sample_data_package(balance_ok=True))

    assert model.check_balance() is True
    income = model.build_income_statement()
    assert list(income.columns) == ["Revenue", "COGS", "GrossProfit", "OpEx", "EBITDA", "DA", "EBIT", "InterestExpense", "TaxExpense", "NetIncome"]
    cash_flow = model.build_cash_flow_statement()
    balance_sheet = model.build_balance_sheet()
    assert pytest.approx(float(cash_flow.iloc[-1]["EndingCash"]), rel=0, abs=1e-6) == float(balance_sheet.iloc[-1]["Cash"])


def test_balance_check_fails_on_bad_data(monkeypatch, tmp_path):
    """A deliberately inconsistent opening balance sheet must fail validation."""

    financial_model, _, _, _, _ = _reload_modules(monkeypatch, tmp_path)
    model = financial_model.ThreeStatementModel(_sample_data_package(balance_ok=False))

    assert model.check_balance() is False


def test_wacc_in_plausible_range(monkeypatch, tmp_path):
    """The modeled WACC should stay within a realistic U.S. equity range."""

    financial_model, _, _, _, _ = _reload_modules(monkeypatch, tmp_path)
    model = financial_model.ThreeStatementModel(_sample_data_package(balance_ok=True))

    wacc = model.compute_wacc()
    assert 0.05 <= wacc <= 0.20


def test_bear_case_revenue_below_base(monkeypatch, tmp_path):
    """Bear-case free cash flow should stay below the base case in every year."""

    financial_model, _, _, _, _ = _reload_modules(monkeypatch, tmp_path)
    model = financial_model.ThreeStatementModel(_sample_data_package(balance_ok=True))

    bear = model.run_scenario("bear")
    base = model.run_scenario("base")

    assert len(bear["fcf"]) == 5
    assert len(base["fcf"]) == 5
    for bear_fcf, base_fcf in zip(bear["fcf"], base["fcf"]):
        assert bear_fcf < base_fcf


def test_scenarios_yaml_has_all_three_cases():
    """The scenarios config must contain bear, base, and bull cases."""

    loaded = yaml.safe_load(Path("config/scenarios.yaml").read_text(encoding="utf-8"))
    assert set(loaded) == {"bear", "base", "bull"}


def test_av2_fatal_error_on_unbalanced_model(monkeypatch, tmp_path):
    """The AV2 agent must DLQ and raise when the opening data is unbalanced."""

    _, av2_model, busmod, _, db_url = _reload_modules(monkeypatch, tmp_path)
    _create_tables(db_url)
    client = fakeredis.FakeRedis()
    bus = busmod.RedisStreamsBus(client, db_url=db_url)

    data_package_id = "dp-1"
    _seed_data_package(db_url, data_package_id, _sample_data_package(balance_ok=False))

    message = _build_message(busmod, data_package_id)

    agent = av2_model.AV2ModelAgent(bus=bus, db=create_engine(db_url), settings=importlib.import_module("core.config").settings)

    calls = {"count": 0}

    def consume_once(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return [message]
        raise StopIteration

    monkeypatch.setattr(bus, "consume", consume_once)

    with pytest.raises(Exception) as exc_info:
        agent.process(message)
    assert exc_info.value.__class__.__name__ == "FatalError"
    assert str(exc_info.value) == "model_balance_failure"

    bus.publish_dlq("model_balance_failure", message.stream, message.data, message.pipeline_run_id)

    with create_engine(db_url).connect() as conn:
        row = conn.execute(text("SELECT reason FROM dlq_entries LIMIT 1")).fetchone()
        assert row[0] == "model_balance_failure"
    assert client.xlen("dlq:failed") >= 1


def test_av2_persists_financial_model_idempotently(monkeypatch, tmp_path):
    """Processing the same AV2 message twice should update one financial model row."""

    _, av2_model, busmod, _, db_url = _reload_modules(monkeypatch, tmp_path)
    _create_tables(db_url)

    data_package_id = "dp-2"
    _seed_data_package(db_url, data_package_id, _sample_data_package(balance_ok=True))
    message = _build_message(busmod, data_package_id)

    agent = av2_model.AV2ModelAgent(bus=busmod.RedisStreamsBus(fakeredis.FakeRedis(), db_url=db_url), db=create_engine(db_url), settings=importlib.import_module("core.config").settings)

    first = agent.process(message)
    second = agent.process(message)

    assert first.model_id == second.model_id
    with create_engine(db_url).connect() as conn:
        rows = conn.execute(text("SELECT model_id, run_id FROM financial_models WHERE run_id = :run_id"), {"run_id": "run-1"}).fetchall()
    assert len(rows) == 1
