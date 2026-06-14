import json
from pathlib import Path
import sqlite3
from sqlalchemy import text
from data import edgar
from core import auditor_flags

from agents.av1_data import AV1DataAgent
from core.bus import InMemoryBus, Message
from core.schemas import M4ScreenOutput


def test_parse_xbrl_fixture():
    p = Path("tests/fixtures/aapl_10k_excerpt.xml")
    parsed = edgar.parse_xbrl_file(p)
    assert parsed.get("revenue") == 1000000000.0
    assert parsed.get("net_income") == 200000000.0


def test_auditor_flag_detection():
    texts = ["There is substantial doubt about the ability to continue"]
    flags = auditor_flags.scan_texts_for_flags(texts)
    assert "going_concern" in flags


def make_agent(tmp_path):
    # sqlite in-memory via SQLAlchemy engine can be created via connection string
    from sqlalchemy import create_engine

    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS data_packages ("
                "data_package_id TEXT PRIMARY KEY, run_id TEXT, ticker TEXT, fetched_at TEXT, payload TEXT)"
            )
        )
    bus = InMemoryBus()
    # Provide a minimal dummy settings object to satisfy BaseAgent ctor
    settings = type("S", (), {})()
    agent = AV1DataAgent(bus=bus, db=engine, settings=settings)
    return agent, bus, engine


def test_agent_persists_and_publishes(monkeypatch):
    agent, bus, engine = make_agent(None)

    # Monkeypatch edgar.fetch_filings to return our fixture and parse_xbrl_file to use it
    fixture = Path("tests/fixtures/aapl_10k_excerpt.xml").resolve()

    def fake_fetch(ticker, filing_types=None, count=4):
        return [str(fixture)]

    monkeypatch.setattr(edgar, "fetch_filings", fake_fetch)

    # Create a simple M4 payload
    m4 = M4ScreenOutput.model_validate({
        "candidates": [{"ticker": "AAPL", "rationale": "example"}],
    })

    # Build a Message envelope similar to other tests. Include primary_sector
    # on the outer envelope data so the agent can infer peers if needed.
    msg = Message(
        id="1",
        stream="stage:rs3:output",
        data={"primary_sector": "Technology", "pipeline_run_id": "run-1"},
        pipeline_run_id="run-1",
        ticker="AAPL",
        trigger_type="manual",
        timestamp=None,
        payload=m4.model_dump(),
        metadata={},
    )

    # Run process
    m5 = agent.process(msg)
    m5_retry = agent.process(msg)

    # Check DB row
    from sqlalchemy import text

    with engine.begin() as conn:
        rows = conn.execute(text("SELECT data_package_id, ticker, payload FROM data_packages")).fetchall()
        assert len(rows) == 1
        dp = json.loads(rows[0][2])
        assert dp["ticker"] == "AAPL"
        assert "filings" in dp

    # Ensure M5 has correct ticker and data_package_id
    assert m5.ticker == "AAPL"
    assert m5.data_package_id is not None
    assert m5_retry.data_package_id == m5.data_package_id
