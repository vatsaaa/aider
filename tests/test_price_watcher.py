"""Tests for the `triggers.price_watcher.PriceWatcher` implementation."""

from __future__ import annotations

import importlib
import sys
from datetime import datetime, timezone

import sqlalchemy
from sqlalchemy import text


def _reload(monkeypatch, tmp_path):
    db_url = f"sqlite:///{tmp_path / 'price_watcher.db'}"
    monkeypatch.setenv("AIDER_DATABASE_URL", db_url)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    monkeypatch.setenv("FRED_API_KEY", "dummy")
    monkeypatch.setenv("SEC_USER_AGENT", "Test User test@example.com")
    monkeypatch.setenv("ENV", "development")

    for name in ["triggers.price_watcher", "core.config", "core"]:
        if name in sys.modules:
            del sys.modules[name]

    mod = importlib.import_module("triggers.price_watcher")
    engine = sqlalchemy.create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS pipeline_runs (run_id TEXT PRIMARY KEY, ticker TEXT, trigger_type TEXT, status TEXT, started_at DATETIME, completed_at DATETIME, git_commit_hash TEXT)"))
        conn.execute(text("CREATE TABLE IF NOT EXISTS published_reports (run_id TEXT, ticker TEXT, target_price REAL, rating TEXT, published_at DATETIME)"))
        conn.execute(text("CREATE TABLE IF NOT EXISTS coverage_universe (ticker TEXT PRIMARY KEY, notes TEXT)"))
        conn.execute(text("CREATE TABLE IF NOT EXISTS price_snapshots (ticker TEXT, price REAL, snapped_at DATETIME, source TEXT)"))

    return mod, engine


def test_price_watcher_triggers_on_move(monkeypatch, tmp_path):
    mod, engine = _reload(monkeypatch, tmp_path)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO pipeline_runs (run_id, ticker, trigger_type, status, started_at, completed_at) VALUES ('run-AAPL', 'AAPL', 'manual', 'complete', '2026-01-01', '2026-01-01')"))
        conn.execute(text("INSERT INTO published_reports (run_id, ticker, target_price, rating, published_at) VALUES ('run-AAPL', 'AAPL', 100.0, 'BUY', '2026-01-01')"))
        conn.execute(text("INSERT INTO coverage_universe (ticker, notes) VALUES ('AAPL', '{\"price_trigger_pct\": 5.0}')"))

    class FakeTicker:
        def __init__(self, ticker):
            self.ticker = ticker

        @property
        def info(self):
            return {"currentPrice": 110.0}

    monkeypatch.setattr(mod.yf, "Ticker", lambda ticker: FakeTicker(ticker))

    watcher = mod.PriceWatcher(db=engine, settings=importlib.import_module("core.config").settings)
    events = watcher.poll()

    assert len(events) == 1
    assert events[0].ticker == "AAPL"


def test_price_watcher_no_trigger_within_threshold(monkeypatch, tmp_path):
    mod, engine = _reload(monkeypatch, tmp_path)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO pipeline_runs (run_id, ticker, trigger_type, status, started_at, completed_at) VALUES ('run-MSFT', 'MSFT', 'manual', 'complete', '2026-01-01', '2026-01-01')"))
        conn.execute(text("INSERT INTO published_reports (run_id, ticker, target_price, rating, published_at) VALUES ('run-MSFT', 'MSFT', 100.0, 'HOLD', '2026-01-01')"))
        conn.execute(text("INSERT INTO coverage_universe (ticker, notes) VALUES ('MSFT', '{\"price_trigger_pct\": 5.0}')"))

    class FakeTicker:
        def __init__(self, ticker):
            self.ticker = ticker

        @property
        def info(self):
            return {"currentPrice": 102.0}

    monkeypatch.setattr(mod.yf, "Ticker", lambda ticker: FakeTicker(ticker))

    watcher = mod.PriceWatcher(db=engine, settings=importlib.import_module("core.config").settings)
    events = watcher.poll()

    assert events == []


def test_price_watcher_does_not_poll_outside_market_hours(monkeypatch, tmp_path):
    mod, engine = _reload(monkeypatch, tmp_path)

    class SpyTicker:
        def __init__(self, ticker):
            raise RuntimeError("should not be called")

    monkeypatch.setattr(mod.yf, "Ticker", SpyTicker)

    # Saturday 10am ET
    saturday = datetime(2026, 5, 30, 10, 0, tzinfo=timezone.utc).astimezone(mod.pytz.timezone("America/New_York"))
    watcher = mod.PriceWatcher(db=engine, settings=importlib.import_module("core.config").settings)
    assert watcher._within_market_hours(moment=saturday) is False
