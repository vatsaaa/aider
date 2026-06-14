"""Integration coverage for the PM1 revision DLQ path."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text


def _create_tables(engine) -> None:
    """Create the minimal PM1 tables used by the revision test."""

    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS reports ("
                "report_id TEXT PRIMARY KEY, run_id TEXT, model_id TEXT, ticker TEXT, iteration INTEGER, status TEXT, draft_md TEXT, final_md TEXT, rating TEXT, target_price REAL, created_at TEXT)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS dlq_entries ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, stream TEXT NOT NULL, message_id TEXT, reason TEXT, payload TEXT, created_at TEXT)"
            )
        )


def test_max_revisions_sends_to_dlq(fake_bus, mock_llm_router, tmp_path) -> None:
    """A third revision should fail fast and write one DLQ entry."""

    from agents.pm1_thesis import PM1ThesisAgent
    from core.bus import Message
    from core.exceptions import FatalError

    db_url = fake_bus._db_url
    engine = create_engine(db_url, future=True)
    _create_tables(engine)

    run_id = "run-pm1-1"
    model_id = "model-pm1-1"
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO reports (report_id, run_id, model_id, ticker, iteration, status, draft_md, final_md, rating, target_price, created_at) "
                "VALUES (:report_id, :run_id, :model_id, :ticker, :iteration, :status, :draft_md, :final_md, :rating, :target_price, :created_at)"
            ),
            {
                "report_id": "report-1",
                "run_id": run_id,
                "model_id": model_id,
                "ticker": "AAPL",
                "iteration": 3,
                "status": "draft",
                "draft_md": "# AAPL — BUY | Target: $212.34 | 2026-05-31",
                "final_md": None,
                "rating": "BUY",
                "target_price": 212.34,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    agent = PM1ThesisAgent(bus=fake_bus, db=engine, settings=SimpleNamespace(MAX_REVISION_ITERATIONS=3))
    revision_message = Message(
        id="msg-revision",
        stream="critic:revision:input",
        data={"payload": {"issues": ["Wrong target price math"]}, "pipeline_run_id": run_id, "ticker": "AAPL"},
        pipeline_run_id=run_id,
        ticker="AAPL",
        trigger_type="manual",
        timestamp=datetime.now(timezone.utc).isoformat(),
        payload={"issues": ["Wrong target price math"]},
        metadata={"retry_count": 0},
    )

    caught_error = None
    try:
        agent._handle_message(revision_message, "critic:revision:input")
    except FatalError as error:
        caught_error = error

    assert caught_error is not None
    assert caught_error.reason == "max_revisions_exceeded"

    assert fake_bus.get_stream_length("dlq:failed") == 1
    with engine.connect() as conn:
        reason = conn.execute(text("SELECT reason FROM dlq_entries LIMIT 1")).scalar_one()
    assert reason == "max_revisions_exceeded"