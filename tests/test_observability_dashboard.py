from __future__ import annotations

import importlib
import sys
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text


def _reload_health_module(monkeypatch, tmp_path):
    db_url = f"sqlite:///{tmp_path / 'observability.db'}"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setenv("AIDER_DATABASE_URL", db_url)
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    monkeypatch.setenv("FRED_API_KEY", "dummy")
    monkeypatch.setenv("SEC_USER_AGENT", "Test User test@example.com")
    monkeypatch.setenv("RUN_ALERT_STALE_MINUTES", "30")

    for name in ["monitor.health", "core.config", "core"]:
        if name in sys.modules:
            del sys.modules[name]

    health_mod = importlib.import_module("monitor.health")
    return health_mod, db_url


def _create_tables(db_url: str) -> None:
    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE pipeline_runs (run_id TEXT PRIMARY KEY, ticker TEXT, trigger_type TEXT, status TEXT, started_at TEXT, completed_at TEXT, git_commit_hash TEXT)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE dlq_entries (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, stream TEXT, message_id TEXT, reason TEXT, payload TEXT, created_at TEXT)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE alerts_failures (id INTEGER PRIMARY KEY AUTOINCREMENT, channel TEXT, payload TEXT, error_message TEXT, failed_at TEXT)"
            )
        )

        stale_started = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        fresh_started = datetime.now(timezone.utc).isoformat()
        conn.execute(
            text(
                "INSERT INTO pipeline_runs (run_id, ticker, trigger_type, status, started_at) VALUES (:r, :t, 'manual', :s, :started_at)"
            ),
            {"r": "run-stale", "t": "AAPL", "s": "started", "started_at": stale_started},
        )
        conn.execute(
            text(
                "INSERT INTO pipeline_runs (run_id, ticker, trigger_type, status, started_at, completed_at) VALUES (:r, :t, 'manual', :s, :started_at, :completed_at)"
            ),
            {
                "r": "run-complete",
                "t": "MSFT",
                "s": "complete",
                "started_at": fresh_started,
                "completed_at": fresh_started,
            },
        )
        conn.execute(
            text(
                "INSERT INTO dlq_entries (run_id, stream, message_id, reason, payload, created_at) VALUES ('run-stale', 'stage:av1:output', '1-0', 'example_failure', '{}', CURRENT_TIMESTAMP)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO alerts_failures (channel, payload, error_message, failed_at) VALUES ('slack', '{}', 'timeout', CURRENT_TIMESTAMP)"
            )
        )


def test_observability_snapshot_and_dashboard(monkeypatch, tmp_path):
    health_mod, db_url = _reload_health_module(monkeypatch, tmp_path)
    _create_tables(db_url)

    client = TestClient(health_mod.app)

    snapshot = client.get("/api/observability").json()
    assert snapshot["pipeline"]["total"] == 2
    assert snapshot["pipeline"]["complete"] == 1
    assert snapshot["pipeline"]["started"] == 1
    assert snapshot["dlq"]["total"] == 1
    assert snapshot["alerts"]["failed"] == 1
    assert len(snapshot["stale_runs"]) == 1
    assert snapshot["stale_runs"][0]["run_id"] == "run-stale"

    html = client.get("/dashboard").text
    assert "Pipeline dashboard" in html
    assert "Total Runs" in html
    assert "run-stale" in html
    assert "example_failure" in html
    assert "Alert delivery failures" in html


def test_root_aliases_dashboard(monkeypatch, tmp_path):
    health_mod, db_url = _reload_health_module(monkeypatch, tmp_path)
    _create_tables(db_url)

    client = TestClient(health_mod.app)
    response = client.get("/")
    assert response.status_code == 200
    assert "Pipeline dashboard" in response.text
