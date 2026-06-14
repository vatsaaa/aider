"""Tests for the coverage monitor daemon."""

from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime, timedelta, timezone

import sqlalchemy
from sqlalchemy import text


def _reload_monitor(monkeypatch, tmp_path):
    """Reload the monitor stack against a temporary SQLite database."""

    db_url = f"sqlite:///{tmp_path / 'coverage_monitor.db'}"
    monkeypatch.setenv("AIDER_DATABASE_URL", db_url)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    monkeypatch.setenv("FRED_API_KEY", "dummy")
    monkeypatch.setenv("SEC_USER_AGENT", "Test User test@example.com")
    monkeypatch.setenv("SMTP_HOST", "mailhog")
    monkeypatch.setenv("SMTP_PORT", "1025")
    monkeypatch.setenv("SMTP_FROM", "analyst@localhost")
    monkeypatch.setenv("SMTP_TO", "alpha@localhost,beta@localhost")
    monkeypatch.setenv("GIT_REPO_PATH", str(tmp_path / "repo"))
    monkeypatch.setenv("ENV", "development")

    for name in ["monitor.coverage_loop", "core.config", "core"]:
        if name in sys.modules:
            del sys.modules[name]

    busmod = importlib.import_module("core.bus")
    monitor_mod = importlib.import_module("monitor.coverage_loop")
    return busmod, monitor_mod, db_url


def _seed_tables(engine, *, ticker: str, target_price: float, rating: str, current_price_trigger_pct: float = 5.0, published_at: datetime | None = None) -> None:
    """Create the minimal schema and seed one coverage row."""

    published_at = published_at or datetime.now(timezone.utc) - timedelta(days=1)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS pipeline_runs (run_id TEXT PRIMARY KEY, ticker TEXT, trigger_type TEXT, status TEXT, started_at DATETIME, completed_at DATETIME, git_commit_hash TEXT)"))
        conn.execute(text("CREATE TABLE IF NOT EXISTS published_reports (run_id TEXT, ticker TEXT, target_price REAL, rating TEXT, published_at DATETIME)"))
        conn.execute(text("CREATE TABLE IF NOT EXISTS coverage_universe (ticker TEXT PRIMARY KEY, notes TEXT)"))
        conn.execute(text("CREATE TABLE IF NOT EXISTS price_snapshots (ticker TEXT, price REAL, snapped_at DATETIME, source TEXT)"))
        conn.execute(text("INSERT INTO pipeline_runs (run_id, ticker, trigger_type, status, started_at, completed_at) VALUES (:run_id, :ticker, 'manual', 'complete', :started_at, :completed_at)"), {
            "run_id": f"run-{ticker}",
            "ticker": ticker,
            "started_at": published_at.isoformat(),
            "completed_at": published_at.isoformat(),
        })
        conn.execute(text("INSERT INTO published_reports (run_id, ticker, target_price, rating, published_at) VALUES (:run_id, :ticker, :target_price, :rating, :published_at)"), {
            "run_id": f"run-{ticker}",
            "ticker": ticker,
            "target_price": target_price,
            "rating": rating,
            "published_at": published_at.isoformat(),
        })
        conn.execute(text("INSERT INTO coverage_universe (ticker, notes) VALUES (:ticker, :notes)"), {
            "ticker": ticker,
            "notes": json.dumps({"price_trigger_pct": current_price_trigger_pct}),
        })


def test_coverage_monitor_retriggers_on_price_move(monkeypatch, tmp_path):
    """A 10% move against a 5% threshold should publish an M1."""

    busmod, monitor_mod, db_url = _reload_monitor(monkeypatch, tmp_path)
    engine = sqlalchemy.create_engine(db_url)
    _seed_tables(engine, ticker="AAPL", target_price=100.0, rating="BUY")

    class FakeTicker:
        """Return a fixed quote for the requested symbol."""

        def __init__(self, ticker):
            self.ticker = ticker

        @property
        def info(self):
            return {"currentPrice": 110.0}

    monkeypatch.setattr(monitor_mod.yf, "Ticker", lambda ticker: FakeTicker(ticker))

    bus = busmod.InMemoryBus()
    monitor = monitor_mod.CoverageMonitor(bus=bus, db=engine, settings=importlib.import_module("core.config").settings)

    events = monitor.poll_price_moves()

    assert len(events) == 1
    assert bus.get_stream_length("trigger:events") == 1
    payload = bus.read("trigger:events", count=1)[0]["message"]
    assert payload["payload"]["ticker"] == "AAPL"


def test_coverage_monitor_no_trigger_within_threshold(monkeypatch, tmp_path):
    """A 2% move should stay below the trigger threshold and publish nothing."""

    busmod, monitor_mod, db_url = _reload_monitor(monkeypatch, tmp_path)
    engine = sqlalchemy.create_engine(db_url)
    _seed_tables(engine, ticker="MSFT", target_price=100.0, rating="BUY")

    class FakeTicker:
        """Return a fixed quote for the requested symbol."""

        def __init__(self, ticker):
            self.ticker = ticker

        @property
        def info(self):
            return {"currentPrice": 102.0}

    monkeypatch.setattr(monitor_mod.yf, "Ticker", lambda ticker: FakeTicker(ticker))

    bus = busmod.InMemoryBus()
    monitor = monitor_mod.CoverageMonitor(bus=bus, db=engine, settings=importlib.import_module("core.config").settings)

    events = monitor.poll_price_moves()

    assert events == []
    assert bus.get_stream_length("trigger:events") == 0


def test_weekly_digest_email_contains_all_covered_tickers(monkeypatch, tmp_path):
    """The digest email body should list every covered ticker."""

    busmod, monitor_mod, db_url = _reload_monitor(monkeypatch, tmp_path)
    engine = sqlalchemy.create_engine(db_url)

    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS pipeline_runs (run_id TEXT PRIMARY KEY, ticker TEXT, trigger_type TEXT, status TEXT, started_at DATETIME, completed_at DATETIME, git_commit_hash TEXT)"))
        conn.execute(text("CREATE TABLE IF NOT EXISTS published_reports (run_id TEXT, ticker TEXT, target_price REAL, rating TEXT, published_at DATETIME)"))
        conn.execute(text("CREATE TABLE IF NOT EXISTS coverage_universe (ticker TEXT PRIMARY KEY, notes TEXT)"))
        conn.execute(text("CREATE TABLE IF NOT EXISTS price_snapshots (ticker TEXT, price REAL, snapped_at DATETIME, source TEXT)"))
        tickers = ["AAPL", "MSFT", "NVDA"]
        for ticker in tickers:
            published_at = datetime.now(timezone.utc) - timedelta(days=2)
            conn.execute(text("INSERT INTO pipeline_runs (run_id, ticker, trigger_type, status, started_at, completed_at) VALUES (:run_id, :ticker, 'manual', 'complete', :published_at, :published_at)"), {"run_id": f"run-{ticker}", "ticker": ticker, "published_at": published_at.isoformat()})
            conn.execute(text("INSERT INTO published_reports (run_id, ticker, target_price, rating, published_at) VALUES (:run_id, :ticker, :target_price, :rating, :published_at)"), {"run_id": f"run-{ticker}", "ticker": ticker, "target_price": 100.0, "rating": "HOLD", "published_at": published_at.isoformat()})
            conn.execute(text("INSERT INTO coverage_universe (ticker, notes) VALUES (:ticker, :notes)"), {"ticker": ticker, "notes": json.dumps({"price_trigger_pct": 5.0})})

    class FakeTicker:
        """Return a fixed price for every symbol."""

        def __init__(self, ticker):
            self.ticker = ticker

        @property
        def info(self):
            prices = {"AAPL": 101.0, "MSFT": 202.0, "NVDA": 303.0}
            return {"currentPrice": prices[self.ticker]}

    monkeypatch.setattr(monitor_mod.yf, "Ticker", lambda ticker: FakeTicker(ticker))

    sent = {}

    class FakeSMTP:
        """Capture the digest message instead of sending it."""

        def __init__(self, host, port):
            sent["host"] = host
            sent["port"] = port

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def login(self, user, password):
            sent["login"] = (user, password)

        def send_message(self, message):
            sent["message"] = message

    bus = busmod.InMemoryBus()
    monitor = monitor_mod.CoverageMonitor(
        bus=bus,
        db=engine,
        settings=importlib.import_module("core.config").settings,
        smtp_factory=FakeSMTP,
    )

    body = monitor.send_weekly_digest()

    assert "AAPL" in body
    assert "MSFT" in body
    assert "NVDA" in body
    assert "AAPL" in sent["message"].as_string()
    assert "MSFT" in sent["message"].as_string()
    assert "NVDA" in sent["message"].as_string()
