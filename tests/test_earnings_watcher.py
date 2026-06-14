"""Tests for the earnings watcher."""

from __future__ import annotations

import importlib
import sys
from datetime import datetime, timedelta, timezone

import fakeredis
from sqlalchemy import create_engine, text


def _reload_modules(monkeypatch, tmp_path):
    """Reload the watcher modules with a temporary SQLite database."""

    db_url = f"sqlite:///{tmp_path / 'earnings.db'}"
    monkeypatch.setenv("AIDER_DATABASE_URL", db_url)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    monkeypatch.setenv("FRED_API_KEY", "dummy")
    monkeypatch.setenv("SEC_USER_AGENT", "Test User test@example.com")
    monkeypatch.setenv("ENV", "development")

    for name in ["triggers.earnings_watcher", "core.config", "core", "yfinance"]:
        if name in sys.modules:
            del sys.modules[name]

    busmod = importlib.import_module("core.bus")
    watcher_mod = importlib.import_module("triggers.earnings_watcher")
    return busmod, watcher_mod, db_url


def _create_tables(db_url: str) -> None:
    """Create the minimal tables required by the watcher."""

    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE coverage_universe ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "ticker TEXT UNIQUE NOT NULL,"
                "added_at TEXT,"
                "notes TEXT)"
            )
        )


def _seed_coverage(db_url: str, tickers: list[str]) -> None:
    """Insert covered tickers used by the watcher."""

    engine = create_engine(db_url)
    with engine.begin() as conn:
        for ticker in tickers:
            conn.execute(text("INSERT INTO coverage_universe (ticker) VALUES (:ticker)"), {"ticker": ticker})


def test_earnings_watcher_publishes_24hr_before(monkeypatch, tmp_path):
    """An earnings date within 24 hours should publish an M1 event."""

    busmod, watcher_mod, db_url = _reload_modules(monkeypatch, tmp_path)
    _create_tables(db_url)
    _seed_coverage(db_url, ["AAPL"])
    bus = busmod.RedisStreamsBus(fakeredis.FakeRedis(), db_url=db_url)

    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)

    class FakeTicker:
        """Stand-in for yfinance.Ticker used by the test."""

        def __init__(self, ticker):
            self.calendar = {"Earnings Date": [tomorrow]}

    monkeypatch.setattr(watcher_mod.yf, "Ticker", FakeTicker)

    watcher = watcher_mod.EarningsWatcher(bus=bus, db=create_engine(db_url), settings=importlib.import_module("core.config").settings)
    events = watcher.poll()

    assert len(events) == 1
    assert events[0].ticker == "AAPL"
    assert events[0].trigger_type == "earnings"
    assert bus.get_stream_length("trigger:events") == 1


def test_earnings_watcher_deduplicates(monkeypatch, tmp_path):
    """The same ticker/date pair should only publish once."""

    busmod, watcher_mod, db_url = _reload_modules(monkeypatch, tmp_path)
    _create_tables(db_url)
    _seed_coverage(db_url, ["AAPL"])
    client = fakeredis.FakeRedis()
    bus = busmod.RedisStreamsBus(client, db_url=db_url)

    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)

    class FakeTicker:
        """Stand-in for yfinance.Ticker used by the test."""

        def __init__(self, ticker):
            self.calendar = {"Earnings Date": [tomorrow]}

    monkeypatch.setattr(watcher_mod.yf, "Ticker", FakeTicker)

    watcher = watcher_mod.EarningsWatcher(bus=bus, db=create_engine(db_url), settings=importlib.import_module("core.config").settings)
    watcher.poll()
    watcher.poll()

    assert bus.get_stream_length("trigger:events") == 1
    assert client.exists(f"earnings_triggered:AAPL:{tomorrow.date().isoformat()}") == 1
