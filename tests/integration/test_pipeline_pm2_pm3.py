"""Integration coverage for the PM2 compliance and PM3 publish path."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text


def _create_tables(engine) -> None:
    """Create the minimal compliance and publishing tables."""

    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS pipeline_runs ("
                "run_id TEXT PRIMARY KEY, ticker TEXT, trigger_type TEXT, status TEXT, started_at TEXT, completed_at TEXT, git_commit_hash TEXT)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS reports ("
                "report_id TEXT PRIMARY KEY, run_id TEXT, model_id TEXT, ticker TEXT, iteration INTEGER, status TEXT, draft_md TEXT, final_md TEXT, pdf_path TEXT, rating TEXT, target_price REAL, created_at TEXT)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS financial_models ("
                "model_id TEXT PRIMARY KEY, run_id TEXT, ticker TEXT, built_at TEXT, wacc REAL, scenarios TEXT, balance_ok INTEGER, payload TEXT, sensitivity_table TEXT)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS dlq_entries ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, stream TEXT NOT NULL, message_id TEXT, reason TEXT, payload TEXT, created_at TEXT)"
            )
        )


def _seed_report_and_model(engine, *, run_id: str, model_id: str, draft_md: str, rating: str, target_price: float, current_price: float) -> None:
    """Insert a draft report and the financial model row used by PM2."""

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO reports (report_id, run_id, model_id, ticker, iteration, status, draft_md, final_md, pdf_path, rating, target_price, created_at) "
                "VALUES (:report_id, :run_id, :model_id, :ticker, :iteration, :status, :draft_md, :final_md, :pdf_path, :rating, :target_price, :created_at)"
            ),
            {
                "report_id": f"report-{run_id}",
                "run_id": run_id,
                "model_id": model_id,
                "ticker": "AAPL",
                "iteration": 1,
                "status": "draft",
                "draft_md": draft_md,
                "final_md": None,
                "pdf_path": None,
                "rating": rating,
                "target_price": target_price,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        conn.execute(
            text(
                "INSERT INTO financial_models (model_id, run_id, ticker, built_at, wacc, scenarios, balance_ok, payload, sensitivity_table) "
                "VALUES (:model_id, :run_id, :ticker, :built_at, :wacc, :scenarios, :balance_ok, :payload, :sensitivity_table)"
            ),
            {
                "model_id": model_id,
                "run_id": run_id,
                "ticker": "AAPL",
                "built_at": datetime.now(timezone.utc).isoformat(),
                "wacc": 0.1,
                "scenarios": json.dumps({"base": {"fcf": [1, 2, 3, 4, 5]}}),
                "balance_ok": 1,
                "payload": json.dumps({"current_price": current_price}),
                "sensitivity_table": json.dumps({}),
            },
        )
        conn.execute(
            text(
                "INSERT INTO pipeline_runs (run_id, ticker, trigger_type, status, started_at) "
                "VALUES (:run_id, :ticker, 'manual', 'started', :started_at)"
            ),
            {"run_id": run_id, "ticker": "AAPL", "started_at": datetime.now(timezone.utc).isoformat()},
        )


def _build_message(run_id: str, verdict: str = "PASS", issues: list[str] | None = None):
    """Construct a critique verdict message for PM2."""

    payload = {"run_id": run_id, "verdict": verdict, "issues": issues or []}
    return {
        "message_id": "msg-1",
        "pipeline_run_id": run_id,
        "trigger_type": "manual",
        "ticker": "AAPL",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
        "metadata": {"retry_count": 0},
    }


def _build_message_object(run_id: str, verdict: str = "PASS", issues: list[str] | None = None):
    """Create a lightweight message object with the attributes PM2 expects."""

    payload = _build_message(run_id, verdict=verdict, issues=issues)["payload"]
    return type(
        "Msg",
        (),
        {
            "payload": payload,
            "data": {"payload": payload},
            "pipeline_run_id": run_id,
            "stream": "critique:verdict",
        },
    )()


def test_mnpi_keyword_halts_pipeline(fake_bus, tmp_path) -> None:
    """MNPI text should stop PM2 and send the message to the DLQ."""

    from agents.pm2_compliance import PM2ComplianceAgent
    from core.exceptions import FatalError

    engine = create_engine(fake_bus._db_url, future=True)
    _create_tables(engine)
    run_id = "run-pm2-1"
    _seed_report_and_model(
        engine,
        run_id=run_id,
        model_id="model-pm2-1",
        draft_md="This result is before announcement and should not be public.",
        rating="BUY",
        target_price=130.0,
        current_price=100.0,
    )

    agent = PM2ComplianceAgent(bus=fake_bus, db=engine, settings=SimpleNamespace(DATABASE_URL=fake_bus._db_url))

    with pytest.raises(FatalError) as exc_info:
        agent.process(_build_message_object(run_id, issues=["before announcement"]))

    assert exc_info.value.reason == "mnpi_detected:before announcement"
    assert fake_bus.get_stream_length("dlq:failed") == 1
    with engine.connect() as conn:
        reason = conn.execute(text("SELECT reason FROM dlq_entries LIMIT 1")).scalar_one()
    assert reason == "mnpi_detected:before announcement"


def test_rating_model_mismatch_halts(fake_bus, tmp_path) -> None:
    """A rating that disagrees with the stored price math should hit the DLQ."""

    from agents.pm2_compliance import PM2ComplianceAgent
    from core.exceptions import FatalError

    engine = create_engine(fake_bus._db_url, future=True)
    _create_tables(engine)
    run_id = "run-pm2-2"
    _seed_report_and_model(
        engine,
        run_id=run_id,
        model_id="model-pm2-2",
        draft_md="The stock is a BUY with upside.",
        rating="BUY",
        target_price=95.0,
        current_price=100.0,
    )

    agent = PM2ComplianceAgent(bus=fake_bus, db=engine, settings=SimpleNamespace(DATABASE_URL=fake_bus._db_url))

    with pytest.raises(FatalError) as exc_info:
        agent.process(_build_message_object(run_id))

    assert exc_info.value.reason == "rating_model_mismatch"
    assert fake_bus.get_stream_length("dlq:failed") == 1
    with engine.connect() as conn:
        reason = conn.execute(text("SELECT reason FROM dlq_entries LIMIT 1")).scalar_one()
    assert reason == "rating_model_mismatch"


def test_pdf_contains_run_id(fake_bus, sample_m7_fixture, tmp_path, monkeypatch) -> None:
    """The PM3 receipt should point to a PDF whose filename includes the run id."""

    from agents.pm3_publisher import PM3PublisherAgent
    from core.bus import Message

    engine = create_engine(fake_bus._db_url, future=True)
    _create_tables(engine)

    run_id = "run-pm3-1"
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO reports (report_id, run_id, model_id, ticker, iteration, status, draft_md, final_md, pdf_path, rating, target_price, created_at) "
                "VALUES (:report_id, :run_id, :model_id, :ticker, :iteration, :status, :draft_md, :final_md, :pdf_path, :rating, :target_price, :created_at)"
            ),
            {
                "report_id": "report-pm3-1",
                "run_id": run_id,
                "model_id": sample_m7_fixture["model_id"],
                "ticker": "AAPL",
                "iteration": 1,
                "status": "approved",
                "draft_md": None,
                "final_md": "# AAPL — BUY | Target: $212.34 | 2026-05-31\nFirst page.\n\n## Section 2\nMore text.",
                "pdf_path": None,
                "rating": sample_m7_fixture["rating"],
                "target_price": sample_m7_fixture["target_price"],
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        conn.execute(
            text(
                "INSERT INTO pipeline_runs (run_id, ticker, trigger_type, status, started_at) "
                "VALUES (:run_id, :ticker, 'manual', 'started', :started_at)"
            ),
            {"run_id": run_id, "ticker": "AAPL", "started_at": datetime.now(timezone.utc).isoformat()},
        )

    repo_path = tmp_path / "reports_audit"
    repo_path.mkdir(parents=True, exist_ok=True)
    settings = SimpleNamespace(
        DATABASE_URL=fake_bus._db_url,
        GIT_REPO_PATH=str(repo_path),
        GIT_AUTHOR_NAME="Digital Analyst",
        GIT_AUTHOR_EMAIL="analyst@localhost",
        SMTP_HOST="mailhog",
        SMTP_PORT=1025,
        SMTP_USER=None,
        SMTP_PASSWORD=None,
        SMTP_FROM="analyst@localhost",
        SMTP_TO=["alpha@localhost"],
    )

    fake_pdf = tmp_path / f"{run_id}.pdf"
    fake_pdf.write_bytes(b"PDFDATA")

    import agents.pm3_publisher as pm3_mod

    monkeypatch.setattr(pm3_mod, "render", lambda markdown_text, rid: str(fake_pdf))
    monkeypatch.setattr(
        pm3_mod,
        "subprocess",
        SimpleNamespace(run=lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="deadbeef\n", stderr=b"")),
    )

    sent = {}

    class FakeSMTP:
        """Capture the outbound mail payload instead of sending it."""

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

    monkeypatch.setattr(pm3_mod, "smtplib", SimpleNamespace(SMTP=FakeSMTP))

    agent = PM3PublisherAgent(bus=fake_bus, db=engine, settings=settings)
    message = Message(
        id="msg-pm3-1",
        stream="stage:pm2:output",
        data={"payload": {"run_id": run_id}, "pipeline_run_id": run_id, "ticker": "AAPL"},
        pipeline_run_id=run_id,
        ticker="AAPL",
        trigger_type="manual",
        timestamp=datetime.now(timezone.utc).isoformat(),
        payload={"run_id": run_id},
        metadata={"retry_count": 0},
    )

    receipt = agent.process(message)
    agent.publish_result(receipt, message)

    assert receipt.pdf_path.endswith(f"{run_id}.pdf")
    assert run_id in receipt.pdf_path
    assert fake_bus.get_stream_length("stage:pm3:output") == 1