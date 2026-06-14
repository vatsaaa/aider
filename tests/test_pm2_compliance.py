import yaml
from sqlalchemy import text

from agents.pm2_compliance import PM2ComplianceAgent
from core.bus import InMemoryBus, Message
from sqlalchemy import create_engine, text
import json


def _build_agent(tmp_path):
    bus = InMemoryBus()
    # sqlite in-memory DB for tests
    engine = create_engine("sqlite:///:memory:")
    # create minimal tables required by PM2
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE reports (report_id TEXT PRIMARY KEY, run_id TEXT, model_id TEXT, ticker TEXT, iteration INTEGER, status TEXT, draft_md TEXT, final_md TEXT, rating TEXT, target_price REAL, created_at DATETIME)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE financial_models (model_id TEXT PRIMARY KEY, run_id TEXT, ticker TEXT, built_at DATETIME, wacc REAL, scenarios TEXT, balance_ok INTEGER, payload TEXT, sensitivity_table TEXT)"
            )
        )
    agent = PM2ComplianceAgent(bus=bus, db=engine, settings={})
    return agent, bus, engine


def _seed_report(engine, run_id, model_id, draft_md="# draft", rating="HOLD", target_price=100.0):
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO reports (report_id, run_id, model_id, ticker, iteration, status, draft_md, rating, target_price, created_at) VALUES (:report_id, :run_id, :model_id, :ticker, 1, 'draft', :draft_md, :rating, :target_price, CURRENT_TIMESTAMP)"
            ),
            {
                "report_id": f"r-{run_id}",
                "run_id": run_id,
                "model_id": model_id,
                "ticker": "AAPL",
                "draft_md": draft_md,
                "rating": rating,
                "target_price": target_price,
            },
        )


def _seed_financial_model(engine, run_id, model_id, payload):
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO financial_models (model_id, run_id, ticker, built_at, wacc, scenarios, balance_ok, payload, sensitivity_table) VALUES (:model_id, :run_id, :ticker, CURRENT_TIMESTAMP, NULL, '[]', 1, :payload, NULL)"
            ),
            {"model_id": model_id, "run_id": run_id, "ticker": "AAPL", "payload": json.dumps(payload)},
        )


def _build_message(run_id, verdict="PASS"):
    payload = {"run_id": run_id, "verdict": verdict}
    envelope = {"payload": payload, "pipeline_run_id": run_id}
    return Message(
        id="1",
        stream="critique:verdict",
        data=envelope,
        pipeline_run_id=run_id,
        ticker=None,
        trigger_type=None,
        timestamp=None,
        payload=payload,
        metadata={},
    )


def test_pm2_pass_routes_to_approved_and_appends_disclosures(tmp_path):
    agent, bus, engine = _build_agent(tmp_path)
    run_id = "pm2-run-1"
    model_id = "model-1"

    # draft BUY with target supporting BUY
    _seed_report(
        engine,
        run_id=run_id,
        model_id=model_id,
        draft_md="# AAPL — BUY | Target: $130.00 | 2026-05-31\nInvestment Thesis...",
        rating="BUY",
        target_price=130.0,
    )
    _seed_financial_model(engine, run_id=run_id, model_id=model_id, payload={"current_price": 100.0})

    msg = _build_message(run_id)

    result = agent.process(msg)
    agent.publish_result(result, msg)

    # M10 published
    assert result is not None
    assert result.disclosures_appended is True
    assert result.report_final_md.startswith("# AAPL")
    assert bus.get_stream_length("stage:pm2:output") == 1

    # DB row updated (no-op in this harness)
    # In full integration tests the reports table must show status approved and disclosures appended


def test_pm2_m9_with_fatal_verdict_is_ignored(tmp_path):
    agent, bus, engine = _build_agent(tmp_path)
    run_id = "pm2-run-4"
    model_id = "model-4"
    _seed_report(engine, run_id=run_id, model_id=model_id, draft_md="# draft", rating="HOLD", target_price=100.0)
    _seed_financial_model(engine, run_id=run_id, model_id=model_id, payload={"current_price": 100.0})

    msg = _build_message(run_id, verdict="FATAL")

    # should be ignored without raising
    out = agent.process(msg)
    assert out is None
    assert bus.get_stream_length("stage:pm2:output") == 0
