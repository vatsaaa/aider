import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text

from orchestrator.monitor import OrchestratorMonitor


class FakeRedis:
    def __init__(self):
        # stream_name -> list of (id, fields)
        self._streams = {}
        self.published = {}

    def xrange(self, stream, min='-', max='+'):
        items = self._streams.get(stream, [])
        return list(items)

    def xadd(self, stream, mapping):
        # create incremental id
        seq = len(self._streams.get(stream, [])) + 1
        ts = int(datetime.now(timezone.utc).timestamp() * 1000)
        item_id = f"{ts}-{seq}"
        entry = (item_id.encode(), {b"data": json.dumps(mapping).encode()})
        self._streams.setdefault(stream, []).append(entry)
        # record published
        self.published.setdefault(stream, []).append(mapping)
        return item_id.encode()

    def xdel(self, stream, item_id):
        items = self._streams.get(stream, [])
        new = [it for it in items if (it[0].decode() if isinstance(it[0], bytes) else it[0]) != item_id]
        self._streams[stream] = new

    def set(self, *args, **kwargs):
        return True


def _create_db(engine):
    # minimal tables used by monitor tests
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS pipeline_runs (run_id TEXT PRIMARY KEY, ticker TEXT, trigger_type TEXT, status TEXT, started_at TIMESTAMP, completed_at TIMESTAMP)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS dlq_entries (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, stream TEXT, message_id TEXT, reason TEXT, payload JSON, created_at TIMESTAMP)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS dlq_retries (id INTEGER PRIMARY KEY AUTOINCREMENT, dlq_entry_id TEXT, retried_at TIMESTAMP)"
            )
        )


def test_republish_and_record_retry():
    fake = FakeRedis()
    # put one dlq entry with old timestamp id so it's due for retry
    payload = {"run_id": "run-1", "original_stream": "stage:av1:output", "original_payload": {"x": 1}}
    fake._streams["dlq:failed"] = [(b"1000-0", {b"data": json.dumps(payload).encode()})]

    engine = create_engine("sqlite:///:memory:")
    _create_db(engine)

    monitor = OrchestratorMonitor(poll_interval=1, base_delay_seconds=1, max_attempts=3, redis_client=fake, db_engine=engine)

    # run one poll
    monitor._poll_once()

    # assert republished to original stream
    assert "stage:av1:output" in fake.published
    assert json.loads(fake.published["stage:av1:output"][0]["data"]) == {"x": 1}

    # assert dlq_retries has a row
    with engine.connect() as conn:
        row = conn.execute(text("SELECT dlq_entry_id FROM dlq_retries LIMIT 1")).fetchone()
        assert row is not None


def test_mark_failed_and_alerts(monkeypatch):
    fake = FakeRedis()
    # three dlq entries for same run
    payload1 = {"run_id": "run-2", "original_stream": "stage:av1:output", "original_payload": {"a": 1}}
    payload2 = {"run_id": "run-2", "original_stream": "stage:av1:output", "original_payload": {"b": 2}}
    payload3 = {"run_id": "run-2", "original_stream": "stage:av1:output", "original_payload": {"c": 3}}
    fake._streams["dlq:failed"] = [
        (b"1000-0", {b"data": json.dumps(payload1).encode()}),
        (b"2000-0", {b"data": json.dumps(payload2).encode()}),
        (b"3000-0", {b"data": json.dumps(payload3).encode()}),
    ]

    engine = create_engine("sqlite:///:memory:")
    _create_db(engine)

    # insert pipeline run
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO pipeline_runs (run_id, ticker, trigger_type, status) VALUES (:r, :t, :g, :s)"), {"r": "run-2", "t": "TICK", "g": "manual", "s": "started"})

    monitor = OrchestratorMonitor(poll_interval=1, base_delay_seconds=1, max_attempts=3, redis_client=fake, db_engine=engine)

    called = {"slack": False, "email": False}

    def fake_slack(alert):
        called["slack"] = True

    def fake_email(alert):
        called["email"] = True

    monkeypatch.setattr(monitor, "_send_slack", fake_slack)
    monkeypatch.setattr(monitor, "_send_email", fake_email)

    monitor._poll_once()

    # pipeline_runs.status should be failed
    with engine.connect() as conn:
        row = conn.execute(text("SELECT status FROM pipeline_runs WHERE run_id = :r"), {"r": "run-2"}).fetchone()
        assert row is not None and row[0] == "failed"

    # alerts published to alerts:human
    assert "alerts:human" in fake.published
    assert called["slack"] is True
    assert called["email"] is True
