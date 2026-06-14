"""Tests for the trigger scanner orchestrator."""

from __future__ import annotations

import importlib
import json
import sys

import fakeredis
from sqlalchemy import create_engine


def _reload_modules(monkeypatch, tmp_path):
    """Reload the scanner stack with a temporary SQLite database."""

    db_url = f"sqlite:///{tmp_path / 'scanner.db'}"
    monkeypatch.setenv("AIDER_DATABASE_URL", db_url)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    monkeypatch.setenv("FRED_API_KEY", "dummy")
    monkeypatch.setenv("SEC_USER_AGENT", "Test User test@example.com")
    monkeypatch.setenv("ENV", "development")

    for name in ["triggers.scanner", "triggers.edgar_watcher", "triggers.fred_watcher", "triggers.earnings_watcher", "core.config", "core"]:
        if name in sys.modules:
            del sys.modules[name]

    busmod = importlib.import_module("core.bus")
    scanner_mod = importlib.import_module("triggers.scanner")
    return busmod, scanner_mod, db_url


def test_scanner_manual_trigger_publishes_m1(monkeypatch, tmp_path):
    """Manual trigger runs should publish an envelope with the M1 payload."""

    busmod, scanner_mod, db_url = _reload_modules(monkeypatch, tmp_path)
    bus = busmod.RedisStreamsBus(fakeredis.FakeRedis(), db_url=db_url)

    class FakeWatcher:
        """Minimal stand-in for watcher constructors."""

        def __init__(self, *args, **kwargs):
            pass

        def poll(self):
            return []

    monkeypatch.setattr(scanner_mod, "EdgarWatcher", FakeWatcher)
    monkeypatch.setattr(scanner_mod, "FredWatcher", FakeWatcher)
    monkeypatch.setattr(scanner_mod, "EarningsWatcher", FakeWatcher)

    scanner = scanner_mod.TriggerScanner(
        bus=bus,
        db=create_engine(db_url),
        settings=importlib.import_module("core.config").settings,
    )

    event = scanner.publish_manual_trigger("AAPL", "manual")

    assert event.ticker == "AAPL"
    assert event.trigger_type == "manual"
    assert bus.get_stream_length("trigger:events") == 1

    stream_entry = bus._client.xrange("trigger:events", count=1)[0][1]
    payload = json.loads(stream_entry[b"data"].decode())
    assert payload["ticker"] == "AAPL"
    assert payload["trigger_type"] == "manual"
    assert payload["payload"]["ticker"] == "AAPL"
    assert payload["payload"]["trigger_type"] == "manual"
    assert payload["metadata"]["source"] == "scanner"
    assert payload["metadata"]["manual"] is True


def test_scanner_schedules_are_registered(monkeypatch, tmp_path):
    """The scanner should register all watcher polling jobs on startup."""

    busmod, scanner_mod, db_url = _reload_modules(monkeypatch, tmp_path)
    bus = busmod.RedisStreamsBus(fakeredis.FakeRedis(), db_url=db_url)

    class FakeWatcher:
        """Minimal stand-in for watcher constructors."""

        def __init__(self, *args, **kwargs):
            pass

        def poll(self):
            return []

    monkeypatch.setattr(scanner_mod, "EdgarWatcher", FakeWatcher)
    monkeypatch.setattr(scanner_mod, "FredWatcher", FakeWatcher)
    monkeypatch.setattr(scanner_mod, "EarningsWatcher", FakeWatcher)

    scanner = scanner_mod.TriggerScanner(
        bus=bus,
        db=create_engine(db_url),
        settings=importlib.import_module("core.config").settings,
    )

    job_ids = {job.id for job in scanner.scheduler.get_jobs()}
    assert job_ids == {"edgar_watcher_poll", "fred_watcher_poll", "earnings_watcher_poll"}