"""Tests for the shared agent base class."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import fakeredis
import pytest
from pydantic import BaseModel
from sqlalchemy import create_engine, text


REQUIRED_ENV = {
    "ANTHROPIC_API_KEY": "dummy",
    "AIDER_DATABASE_URL": "sqlite:///:memory:",
    "REDIS_URL": "redis://localhost:6379",
    "FRED_API_KEY": "dummy",
    "SEC_USER_AGENT": "Test User test@example.com",
}


def _reload_modules(monkeypatch, tmp_path):
    """Reload the core modules with predictable environment variables."""

    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("AIDER_DATABASE_URL", db_url)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    monkeypatch.setenv("FRED_API_KEY", "dummy")
    monkeypatch.setenv("SEC_USER_AGENT", "Test User test@example.com")
    monkeypatch.setenv("ENV", "development")

    for name in ["core.agent_base", "core.exceptions", "core.config", "core", "aider"]:
        if name in sys.modules:
            del sys.modules[name]

    busmod = importlib.import_module("core.bus")
    agentmod = importlib.import_module("core.agent_base")
    return busmod, agentmod, db_url


def _create_dlq_table(db_url: str) -> None:
    """Create the minimal DLQ table required by `publish_dlq`."""

    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS dlq_entries ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "run_id TEXT, stream TEXT NOT NULL, message_id TEXT, reason TEXT, payload TEXT, created_at TEXT)"
            )
        )


def _create_pipeline_runs_table(db_url: str) -> None:
    """Create the minimal pipeline_runs table required by the base agent hook."""

    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS pipeline_runs ("
                "run_id TEXT PRIMARY KEY, ticker TEXT, trigger_type TEXT, status TEXT, started_at TEXT, completed_at TEXT, git_commit_hash TEXT)"
            )
        )


def _create_audit_log_table(db_url: str) -> None:
    """Create the minimal audit_log table required by the audit hook."""

    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS audit_log ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "run_id TEXT, stage TEXT NOT NULL, verdict TEXT, issues TEXT, created_at TEXT)"
            )
        )


class DummyResult(BaseModel):
    """Simple output schema used by the BaseAgent tests."""

    value: str


def _build_agent(agentmod, bus, db_url, process_impl):
    """Construct a small BaseAgent subclass for test scenarios."""

    class DummyAgent(agentmod.BaseAgent):
        stream_in = "trigger:events"
        stream_out = "stage:dummy:output"
        group_name = "dummy-group"
        agent_name = "dummy_agent"

        def process(self, message):
            return process_impl(message)

    engine = create_engine(db_url)
    return DummyAgent(bus=bus, db=engine, settings=importlib.import_module("core.config").settings)


def _publish_input(bus, payload):
    """Publish a message onto the input stream and return the stream id."""

    return bus.publish("trigger:events", payload)


def test_base_agent_happy_path(monkeypatch, tmp_path, capsys):
    """Successful processing should publish, ack, and log JSON output."""

    busmod, agentmod, db_url = _reload_modules(monkeypatch, tmp_path)
    _create_dlq_table(db_url)
    _create_pipeline_runs_table(db_url)
    _create_audit_log_table(db_url)
    client = fakeredis.FakeRedis()
    bus = busmod.RedisStreamsBus(client, db_url=db_url)

    _publish_input(
        bus,
        {
            "message_id": "m1",
            "pipeline_run_id": "run-1",
            "trigger_type": "manual",
            "ticker": "AAPL",
            "timestamp": "2026-05-22T00:00:00Z",
            "payload": {"foo": "bar"},
            "metadata": {"retry_count": 0},
        },
    )

    real_consume = bus.consume
    calls = {"count": 0}

    def consume_once(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_consume(*args, **kwargs)
        raise StopIteration

    monkeypatch.setattr(bus, "consume", consume_once)

    agent = _build_agent(agentmod, bus, db_url, lambda message: DummyResult(value=message.ticker or ""))
    agent.run()

    assert client.xlen("stage:dummy:output") == 1
    output = client.xrange("stage:dummy:output", count=1)[0][1]
    rendered = json.loads(output[b"data"].decode())
    assert rendered["ticker"] == "AAPL"
    assert rendered["payload"] == {"value": "AAPL"}

    pending = client.xpending("trigger:events", "dummy-group")
    assert pending["pending"] == 0

    logs = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert logs
    for line in logs:
        record = json.loads(line)
        assert record["agent_name"] == "dummy_agent"
        assert record["run_id"] == "run-1"
        assert record["ticker"] == "AAPL"

    with create_engine(db_url).connect() as conn:
        row = conn.execute(text("SELECT stage, verdict, issues FROM audit_log LIMIT 1")).fetchone()
        assert row is not None
        assert row[0] == "dummy_agent"
        assert row[1] == "SUCCESS"
        assert json.loads(row[2]) == []


def test_base_agent_fatal_error_routes_to_dlq(monkeypatch, tmp_path):
    """Fatal errors should route to the DLQ and be acknowledged."""

    busmod, agentmod, db_url = _reload_modules(monkeypatch, tmp_path)
    _create_dlq_table(db_url)
    _create_audit_log_table(db_url)
    client = fakeredis.FakeRedis()
    bus = busmod.RedisStreamsBus(client, db_url=db_url)

    _publish_input(
        bus,
        {
            "message_id": "m1",
            "pipeline_run_id": "run-2",
            "trigger_type": "manual",
            "ticker": "MSFT",
            "timestamp": "2026-05-22T00:00:00Z",
            "payload": {"foo": "bar"},
            "metadata": {"retry_count": 0},
        },
    )

    real_consume = bus.consume
    calls = {"count": 0}

    def consume_once(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_consume(*args, **kwargs)
        raise StopIteration

    monkeypatch.setattr(bus, "consume", consume_once)

    def raise_fatal(_message):
        from core.exceptions import FatalError

        raise FatalError("fatal_reason", run_id="run-2")

    agent = _build_agent(agentmod, bus, db_url, raise_fatal)
    agent.run()

    assert client.xlen("dlq:failed") == 1
    pending = client.xpending("trigger:events", "dummy-group")
    assert pending["pending"] == 0

    with create_engine(db_url).connect() as conn:
        row = conn.execute(text("SELECT reason, run_id FROM dlq_entries LIMIT 1")).fetchone()
        assert row[0] == "fatal_reason"
        assert row[1] == "run-2"

        audit_row = conn.execute(text("SELECT stage, verdict, issues FROM audit_log LIMIT 1")).fetchone()
        assert audit_row is not None
        assert audit_row[0] == "dummy_agent"
        assert audit_row[1] == "FATAL"
        assert json.loads(audit_row[2]) == ["fatal_reason"]


def test_base_agent_transient_error_not_acked(monkeypatch, tmp_path):
    """Transient errors must remain pending for Redis redelivery."""

    busmod, agentmod, db_url = _reload_modules(monkeypatch, tmp_path)
    _create_dlq_table(db_url)
    _create_audit_log_table(db_url)
    client = fakeredis.FakeRedis()
    bus = busmod.RedisStreamsBus(client, db_url=db_url)

    _publish_input(
        bus,
        {
            "message_id": "m1",
            "pipeline_run_id": "run-3",
            "trigger_type": "manual",
            "ticker": "NVDA",
            "timestamp": "2026-05-22T00:00:00Z",
            "payload": {"foo": "bar"},
            "metadata": {"retry_count": 0},
        },
    )

    real_consume = bus.consume
    calls = {"count": 0}

    def consume_once(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_consume(*args, **kwargs)
        raise StopIteration

    monkeypatch.setattr(bus, "consume", consume_once)

    def raise_transient(_message):
        raise ValueError("temporary failure")

    agent = _build_agent(agentmod, bus, db_url, raise_transient)
    agent.run()

    pending = client.xpending("trigger:events", "dummy-group")
    assert pending["pending"] == 1
    assert client.xlen("dlq:failed") == 0


def test_base_agent_log_contains_required_fields(monkeypatch, tmp_path, capsys):
    """Every emitted log line should include the required correlation fields."""

    busmod, agentmod, db_url = _reload_modules(monkeypatch, tmp_path)
    _create_dlq_table(db_url)
    client = fakeredis.FakeRedis()
    bus = busmod.RedisStreamsBus(client, db_url=db_url)

    _publish_input(
        bus,
        {
            "message_id": "m1",
            "pipeline_run_id": "run-4",
            "trigger_type": "manual",
            "ticker": "AAPL",
            "timestamp": "2026-05-22T00:00:00Z",
            "payload": {"foo": "bar"},
            "metadata": {"retry_count": 0},
        },
    )

    real_consume = bus.consume
    calls = {"count": 0}

    def consume_once(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_consume(*args, **kwargs)
        raise StopIteration

    monkeypatch.setattr(bus, "consume", consume_once)

    agent = _build_agent(agentmod, bus, db_url, lambda message: DummyResult(value="ok"))
    agent.run()

    records = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert records
    for record in records:
        assert record["agent_name"] == "dummy_agent"
        assert record["run_id"] == "run-4"
        assert record["ticker"] == "AAPL"
        assert "stream" in record


def test_base_agent_inserts_pipeline_run_row(monkeypatch, tmp_path):
    """The shared loop should create the parent pipeline_runs row before processing."""

    busmod, agentmod, db_url = _reload_modules(monkeypatch, tmp_path)
    _create_dlq_table(db_url)
    _create_pipeline_runs_table(db_url)
    client = fakeredis.FakeRedis()
    bus = busmod.RedisStreamsBus(client, db_url=db_url)

    _publish_input(
        bus,
        {
            "message_id": "m1",
            "pipeline_run_id": "run-parent-1",
            "trigger_type": "manual",
            "ticker": "AAPL",
            "timestamp": "2026-05-22T00:00:00Z",
            "payload": {"foo": "bar"},
            "metadata": {"retry_count": 0},
        },
    )

    real_consume = bus.consume
    calls = {"count": 0}

    def consume_once(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_consume(*args, **kwargs)
        raise StopIteration

    monkeypatch.setattr(bus, "consume", consume_once)

    agent = _build_agent(agentmod, bus, db_url, lambda message: DummyResult(value="ok"))
    agent.run()

    with create_engine(db_url).connect() as conn:
        row = conn.execute(text("SELECT run_id, ticker, trigger_type, status FROM pipeline_runs WHERE run_id = :run_id"), {"run_id": "run-parent-1"}).fetchone()

    assert row is not None
    assert row[0] == "run-parent-1"
    assert row[1] == "AAPL"
    assert row[2] == "manual"
    assert row[3] == "started"
