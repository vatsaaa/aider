"""Tests for the Redis Streams bus wrapper."""

from __future__ import annotations

import importlib
import json
import os
import sys
from typing import Iterator

import fakeredis
import pytest
from sqlalchemy import create_engine, text


def _reload_bus_module(monkeypatch, tmp_path, env: str = "development"):
    """Reload core.bus with a temporary SQLite DB and desired ENV."""

    db_path = tmp_path / "test.db"
    db_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("AIDER_DATABASE_URL", db_url)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    monkeypatch.setenv("FRED_API_KEY", "dummy")
    monkeypatch.setenv("SEC_USER_AGENT", "Test User test@example.com")
    monkeypatch.setenv("ENV", env)

    for name in ["core.bus", "core.config", "core"]:
        if name in sys.modules:
            del sys.modules[name]

    return importlib.import_module("core.bus")


def _init_sqlite_dlq_table(db_url: str) -> None:
    """Create a minimal dlq_entries table for DLQ persistence tests."""

    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS dlq_entries ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "run_id TEXT, stream TEXT NOT NULL, message_id TEXT, reason TEXT, payload TEXT, created_at TEXT)"
            )
        )


def test_publish_and_consume(monkeypatch, tmp_path):
    """Publishing a message then consuming it from a group yields the payload."""

    busmod = _reload_bus_module(monkeypatch, tmp_path)
    client = fakeredis.FakeRedis()
    bus = busmod.RedisStreamsBus(client, db_url=f"sqlite:///{tmp_path / 'test.db'}")

    payload = {
        "message_id": "m1",
        "pipeline_run_id": "run-1",
        "trigger_type": "manual",
        "ticker": "AAPL",
        "timestamp": "2026-05-22T00:00:00Z",
        "payload": {"hello": "world"},
        "metadata": {"retry_count": 0},
    }

    msg_id = bus.publish("trigger:events", payload)
    assert msg_id

    msgs = bus.consume("trigger:events", "rs1-group", "consumer-1")
    assert len(msgs) == 1
    assert msgs[0].payload == {"hello": "world"}
    assert msgs[0].ticker == "AAPL"


def test_ack_removes_from_pel(monkeypatch, tmp_path):
    """Acking a consumed message removes it from the pending list."""

    busmod = _reload_bus_module(monkeypatch, tmp_path)
    client = fakeredis.FakeRedis()
    bus = busmod.RedisStreamsBus(client, db_url=f"sqlite:///{tmp_path / 'test.db'}")

    payload = {
        "message_id": "m1",
        "pipeline_run_id": "run-1",
        "trigger_type": "manual",
        "ticker": "AAPL",
        "timestamp": "2026-05-22T00:00:00Z",
        "payload": {"hello": "world"},
        "metadata": {"retry_count": 0},
    }
    bus.publish("trigger:events", payload)
    msgs = bus.consume("trigger:events", "rs1-group", "consumer-1")
    assert msgs
    bus.ack("trigger:events", "rs1-group", msgs[0].id)
    pending = client.xpending("trigger:events", "rs1-group")
    assert pending["pending"] == 0


def test_dlq_publish_writes_to_stream_and_db(monkeypatch, tmp_path):
    """Publishing to the DLQ should write both to Redis and the DB."""

    busmod = _reload_bus_module(monkeypatch, tmp_path)
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    _init_sqlite_dlq_table(db_url)
    client = fakeredis.FakeRedis()
    bus = busmod.RedisStreamsBus(client, db_url=db_url)

    bus.publish_dlq("test_reason", "trigger:events", {"foo": "bar"}, "run-1")

    assert client.xlen("dlq:failed") == 1
    engine = create_engine(db_url)
    with engine.connect() as conn:
        row = conn.execute(text("SELECT reason, stream FROM dlq_entries LIMIT 1")).fetchone()
        assert row[0] == "test_reason"
        assert row[1] == "trigger:events"


def test_flush_stream_raises_in_production(monkeypatch, tmp_path):
    """flush_stream must reject destructive use in non-development envs."""

    busmod = _reload_bus_module(monkeypatch, tmp_path, env="production")
    client = fakeredis.FakeRedis()
    bus = busmod.RedisStreamsBus(client, db_url=f"sqlite:///{tmp_path / 'test.db'}")
    with pytest.raises(RuntimeError):
        bus.flush_stream("trigger:events")


def test_consumer_group_created_on_first_consume(monkeypatch, tmp_path):
    """Consuming from a stream with no group yet should auto-create it."""

    busmod = _reload_bus_module(monkeypatch, tmp_path)
    client = fakeredis.FakeRedis()
    bus = busmod.RedisStreamsBus(client, db_url=f"sqlite:///{tmp_path / 'test.db'}")

    payload = {
        "message_id": "m1",
        "pipeline_run_id": "run-1",
        "trigger_type": "manual",
        "ticker": "AAPL",
        "timestamp": "2026-05-22T00:00:00Z",
        "payload": {"hello": "world"},
        "metadata": {"retry_count": 0},
    }
    bus.publish("trigger:events", payload)
    msgs = bus.consume("trigger:events", "new-group", "consumer-1")
    assert len(msgs) == 1


def test_cache_round_trip(monkeypatch, tmp_path):
    """Cache helpers should persist and retrieve values through the bus wrapper."""

    busmod = _reload_bus_module(monkeypatch, tmp_path)
    client = fakeredis.FakeRedis()
    bus = busmod.RedisStreamsBus(client, db_url=f"sqlite:///{tmp_path / 'test.db'}")

    bus.set_cache("cache:key", json.dumps({"value": 1}), ttl_seconds=60)
    cached = bus.get_cache("cache:key")

    assert cached is not None
    assert json.loads(cached) == {"value": 1}
