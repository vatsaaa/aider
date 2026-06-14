"""Tests for the FRED macro watcher."""

from __future__ import annotations

import importlib
import sys
from datetime import datetime, timezone

import fakeredis
from sqlalchemy import create_engine, text


def _reload_modules(monkeypatch, tmp_path):
    """Reload the watcher modules with a temporary SQLite database."""

    db_url = f"sqlite:///{tmp_path / 'fred.db'}"
    monkeypatch.setenv("AIDER_DATABASE_URL", db_url)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    monkeypatch.setenv("FRED_API_KEY", "dummy")
    monkeypatch.setenv("SEC_USER_AGENT", "Test User test@example.com")
    monkeypatch.setenv("ENV", "development")

    for name in ["triggers.fred_watcher", "core.config", "core", "fredapi"]:
        if name in sys.modules:
            del sys.modules[name]

    busmod = importlib.import_module("core.bus")
    watcher_mod = importlib.import_module("triggers.fred_watcher")
    return busmod, watcher_mod, db_url


def _create_tables(db_url: str) -> None:
    """Create the minimal tables required by the watcher."""

    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE price_snapshots ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "ticker TEXT NOT NULL,"
                "price NUMERIC NOT NULL,"
                "snapped_at TEXT,"
                "source TEXT)"
            )
        )


def test_fred_watcher_publishes_on_value_change(monkeypatch, tmp_path):
    """A new FRED observation should emit an M1 trigger."""

    busmod, watcher_mod, db_url = _reload_modules(monkeypatch, tmp_path)
    _create_tables(db_url)
    bus = busmod.RedisStreamsBus(fakeredis.FakeRedis(), db_url=db_url)

    class FakeFred:
        """Tiny stand-in for fredapi.Fred used in the test."""

        def get_series(self, series_id):
            return [1.0, 2.0] if series_id == "FEDFUNDS" else [1.0]

    monkeypatch.setattr(watcher_mod, "Fred", lambda api_key: FakeFred())
    monkeypatch.setattr(watcher_mod, "FRED_SERIES_IDS", ("FEDFUNDS",))

    watcher = watcher_mod.FredWatcher(bus=bus, db=create_engine(db_url), settings=importlib.import_module("core.config").settings)
    events = watcher.poll()

    assert len(events) == 1
    assert events[0].ticker == "__MACRO__"
    assert events[0].trigger_type == "fred_release"
    assert bus.get_stream_length("trigger:events") == 1


def test_fred_watcher_no_publish_on_no_change(monkeypatch, tmp_path):
    """Identical FRED observations should not create a new trigger."""

    busmod, watcher_mod, db_url = _reload_modules(monkeypatch, tmp_path)
    _create_tables(db_url)
    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO price_snapshots (ticker, price, snapped_at, source) "
                "VALUES ('__MACRO__:FEDFUNDS', 2.0, '2026-05-22T00:00:00Z', 'fred')"
            )
        )

    bus = busmod.RedisStreamsBus(fakeredis.FakeRedis(), db_url=db_url)

    class FakeFred:
        """Tiny stand-in for fredapi.Fred used in the test."""

        def get_series(self, series_id):
            return [2.0, 2.0] if series_id == "FEDFUNDS" else [1.0]

    monkeypatch.setattr(watcher_mod, "Fred", lambda api_key: FakeFred())
    monkeypatch.setattr(watcher_mod, "FRED_SERIES_IDS", ("FEDFUNDS",))

    watcher = watcher_mod.FredWatcher(bus=bus, db=engine, settings=importlib.import_module("core.config").settings)
    events = watcher.poll()

    assert events == []
    assert bus.get_stream_length("trigger:events") == 0

