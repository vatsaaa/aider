"""Tests for the PM1 thesis agent and its prompt templates."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader
from sqlalchemy import create_engine, text

from agents.pm1_thesis import PM1ThesisAgent
from core.bus import InMemoryBus, Message
from core.exceptions import FatalError
from core.schemas import M8DraftReport
from llm.prompt_loader import load_prompt


ROOT = Path(__file__).resolve().parents[1]
PROMPT_DIR = ROOT / "config" / "prompts"


def _create_tables(engine) -> None:
    """Create the minimal PM1 tables required for the tests."""

    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE financial_models ("
                "model_id TEXT PRIMARY KEY,"
                "run_id TEXT,"
                "ticker TEXT,"
                "payload TEXT,"
                "scenarios TEXT,"
                "wacc REAL,"
                "balance_ok INTEGER,"
                "sensitivity_table TEXT"
                ")"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE data_packages ("
                "data_package_id TEXT PRIMARY KEY,"
                "run_id TEXT,"
                "ticker TEXT,"
                "payload TEXT,"
                "fetched_at TEXT"
                ")"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE reports ("
                "report_id TEXT PRIMARY KEY,"
                "run_id TEXT,"
                "model_id TEXT,"
                "ticker TEXT,"
                "iteration INTEGER,"
                "status TEXT,"
                "draft_md TEXT,"
                "final_md TEXT,"
                "rating TEXT,"
                "target_price REAL,"
                "created_at TEXT"
                ")"
            )
        )


def _seed_context(engine, *, run_id: str, model_id: str, ticker: str = "AAPL") -> dict[str, object]:
    """Insert a simple financial model and data package for a single run."""

    valuation = {
        "rating": "BUY",
        "target_price": 212.34,
        "dcf_value": 205.0,
        "peer_multiple_value": 219.68,
        "model_id": model_id,
        "reasoning": "Claude draft reasoning.",
    }
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO financial_models (model_id, run_id, ticker, payload, scenarios, wacc, balance_ok, sensitivity_table) "
                "VALUES (:model_id, :run_id, :ticker, :payload, :scenarios, :wacc, :balance_ok, :sensitivity_table)"
            ),
            {
                "model_id": model_id,
                "run_id": run_id,
                "ticker": ticker,
                "payload": json.dumps({"valuation": valuation, "ticker": ticker}),
                "scenarios": json.dumps({"base": {"fcf": [1, 2, 3, 4, 5]}}),
                "wacc": 0.1,
                "balance_ok": 1,
                "sensitivity_table": json.dumps({}),
            },
        )
        conn.execute(
            text(
                "INSERT INTO data_packages (data_package_id, run_id, ticker, payload, fetched_at) "
                "VALUES (:data_package_id, :run_id, :ticker, :payload, :fetched_at)"
            ),
            {
                "data_package_id": f"dp-{run_id}",
                "run_id": run_id,
                "ticker": ticker,
                "payload": json.dumps({"ticker": ticker, "financials": {"revenue": 100.0}}),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    return valuation


def _build_agent(tmp_path, monkeypatch, *, max_revisions: int = 3):
    """Create a PM1 agent wired to an in-memory bus and SQLite database."""

    db_path = tmp_path / "pm1.db"
    engine = create_engine(f"sqlite:///{db_path}")
    _create_tables(engine)
    bus = InMemoryBus()
    settings = SimpleNamespace(MAX_REVISION_ITERATIONS=max_revisions)
    agent = PM1ThesisAgent(bus=bus, db=engine, settings=settings)
    return agent, bus, engine


def _build_message(*, run_id: str, model_id: str, ticker: str = "AAPL", stream: str = "stage:av3:output") -> Message:
    """Create a synthetic message for the PM1 agent."""

    valuation = {
        "rating": "BUY",
        "target_price": 212.34,
        "dcf_value": 205.0,
        "peer_multiple_value": 219.68,
        "model_id": model_id,
        "reasoning": "Claude draft reasoning.",
    }
    payload = valuation if stream == "stage:av3:output" else {"issues": []}
    return Message(
        id="msg-1",
        stream=stream,
        data={"payload": payload, "pipeline_run_id": run_id, "ticker": ticker},
        pipeline_run_id=run_id,
        ticker=ticker,
        trigger_type="manual",
        timestamp=datetime.now(timezone.utc).isoformat(),
        payload=payload,
        metadata={"retry_count": 0},
    )


def _build_revision_message(*, run_id: str, ticker: str = "AAPL", issues: list[str] | None = None) -> Message:
    """Create a synthetic critic revision message for the PM1 agent."""

    payload = {"issues": issues or ["Wrong target price math"]}
    return Message(
        id="msg-revision",
        stream="critic:revision:input",
        data={"payload": payload, "pipeline_run_id": run_id, "ticker": ticker},
        pipeline_run_id=run_id,
        ticker=ticker,
        trigger_type="manual",
        timestamp=datetime.now(timezone.utc).isoformat(),
        payload=payload,
        metadata={"retry_count": 0},
    )


def _mock_llm_response() -> dict[str, object]:
    """Return a deterministic Claude response for the PM1 tests."""

    return {
        "investment_thesis": "The catalyst is clear and the valuation gap is measurable.",
        "business_model": "The business model combines recurring revenue with operating leverage.",
        "earnings_review": "Results were consistent with consensus and margins remained stable.",
        "risk_factors": "A 50bps move in rates could compress the multiple by 8%.",
        "dcf_detail": "DCF and peer work both support the current target.",
        "peer_comp_table": "Peer multiples are in line with the sector median.",
        "financial_summary_rows": [
            {"metric": "Revenue", "fy_minus_1": "100", "fy_0": "110", "fy_1": "120", "fy_2": "130"},
            {"metric": "EBITDA", "fy_minus_1": "30", "fy_0": "33", "fy_1": "36", "fy_2": "39"},
        ],
        "scenarios": {
            "bear": "Bear case narrative.",
            "base": "Base case narrative.",
            "bull": "Bull case narrative.",
        },
        "sensitivity_table": {
            "9.0%": {"2.0%": 100, "2.5%": 105, "3.0%": 110, "3.5%": 115},
            "10.0%": {"2.0%": 95, "2.5%": 100, "3.0%": 105, "3.5%": 110},
            "11.0%": {"2.0%": 90, "2.5%": 95, "3.0%": 100, "3.5%": 105},
            "12.0%": {"2.0%": 85, "2.5%": 90, "3.0%": 95, "3.5%": 100},
        },
        "sensitivity_growth_rates": ["2.0%", "2.5%", "3.0%", "3.5%"],
    }


def test_pm1_publishes_m8_to_three_streams(tmp_path, monkeypatch) -> None:
    """A draft PM1 message should fan out the same M8 payload to three streams."""

    agent, bus, engine = _build_agent(tmp_path, monkeypatch)
    run_id = "run-1"
    model_id = "model-1"
    _seed_context(engine, run_id=run_id, model_id=model_id)
    message = _build_message(run_id=run_id, model_id=model_id)
    agent.call_llm = lambda **kwargs: _mock_llm_response()

    result = agent.process(message)

    assert result.iteration == 1
    assert bus.get_stream_length("critic:quant:input") == 1
    assert bus.get_stream_length("critic:logic:input") == 1
    assert bus.get_stream_length("critic:data:input") == 1

    published = bus.consume("critic:quant:input", "critic-group", "consumer-1")[0]
    assert published.payload["report_draft_md"] == result.report_draft_md
    assert published.payload["iteration"] == 1


def test_pm1_shared_run_consumes_draft_and_revision_streams(tmp_path, monkeypatch) -> None:
    """PM1 should consume both configured input streams through BaseAgent.run()."""

    agent, bus, _engine = _build_agent(tmp_path, monkeypatch)
    calls: list[str] = []

    def fake_process_message(message: Message, stream_type: str) -> M8DraftReport:
        calls.append(stream_type)
        return M8DraftReport(
            report_draft_md=f"{stream_type}:{message.id}",
            iteration=1,
            model_id="model-shared-run",
            run_id=message.pipeline_run_id or "run-shared",
        )

    agent._process_message = fake_process_message  # type: ignore[method-assign]

    bus.publish(
        "stage:av3:output",
        {
            "message_id": "draft-1",
            "pipeline_run_id": "run-shared",
            "trigger_type": "manual",
            "ticker": "AAPL",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {"rating": "BUY", "target_price": 1.0, "dcf_value": 1.0, "peer_multiple_value": 1.0, "model_id": "model-shared-run", "reasoning": "x"},
            "metadata": {},
        },
    )
    bus.publish(
        "critic:revision:input",
        {
            "message_id": "revision-1",
            "pipeline_run_id": "run-shared",
            "trigger_type": "manual",
            "ticker": "AAPL",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {"issues": ["revise"]},
            "metadata": {},
        },
    )

    real_consume = bus.consume
    calls_seen = {"count": 0}

    def consume_once(*args, **kwargs):
        calls_seen["count"] += 1
        if calls_seen["count"] == 3:
            raise StopIteration
        return real_consume(*args, **kwargs)

    monkeypatch.setattr(bus, "consume", consume_once)

    agent.run()

    assert calls == ["stage:av3:output", "critic:revision:input"]
    pending_draft = bus.get_stream_length("stage:av3:output")
    pending_revision = bus.get_stream_length("critic:revision:input")
    assert pending_draft == 0
    assert pending_revision == 0


def test_pm1_saves_draft_to_db(tmp_path, monkeypatch) -> None:
    """Processing a draft should write a draft row with iteration one."""

    agent, _, engine = _build_agent(tmp_path, monkeypatch)
    run_id = "run-2"
    model_id = "model-2"
    _seed_context(engine, run_id=run_id, model_id=model_id)
    message = _build_message(run_id=run_id, model_id=model_id)
    agent.call_llm = lambda **kwargs: _mock_llm_response()

    agent.process(message)
    agent.process(message)

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT status, iteration, draft_md FROM reports WHERE run_id = :run_id"),
            {"run_id": run_id},
        ).fetchone()
        count = conn.execute(text("SELECT COUNT(*) FROM reports WHERE run_id = :run_id"), {"run_id": run_id}).scalar_one()

    assert row[0] == "draft"
    assert row[1] == 1
    assert "Investment Thesis" in row[2]
    assert count == 1


def test_pm1_handles_revision_increments_iteration(tmp_path, monkeypatch) -> None:
    """A revision message should increment the draft iteration and update the DB row."""

    agent, _, engine = _build_agent(tmp_path, monkeypatch)
    run_id = "run-3"
    model_id = "model-3"
    _seed_context(engine, run_id=run_id, model_id=model_id)
    initial_message = _build_message(run_id=run_id, model_id=model_id)
    revision_message = _build_revision_message(run_id=run_id, issues=["Wrong target price math", "Risk factor not quantified"])
    responses = [_mock_llm_response(), {**_mock_llm_response(), "investment_thesis": "Revised thesis text."}]
    agent.call_llm = lambda **kwargs: responses.pop(0)

    agent.process(initial_message)
    agent.process(revision_message)

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT iteration, draft_md FROM reports WHERE run_id = :run_id"),
            {"run_id": run_id},
        ).fetchone()

    assert row[0] == 2
    assert "Revised thesis text." in row[1]


def test_pm1_max_revisions_routes_to_dlq(tmp_path, monkeypatch) -> None:
    """A revision beyond the configured limit should raise and write to the DLQ."""

    agent, bus, engine = _build_agent(tmp_path, monkeypatch, max_revisions=3)
    run_id = "run-4"
    model_id = "model-4"
    _seed_context(engine, run_id=run_id, model_id=model_id)
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

    revision_message = _build_revision_message(run_id=run_id)
    agent.call_llm = lambda **kwargs: _mock_llm_response()

    try:
        agent._handle_message(revision_message, "critic:revision:input")
        raised = False
    except FatalError as error:
        raised = True
        assert error.reason == "max_revisions_exceeded"

    assert raised is True
    assert bus.get_stream_length("dlq:failed") == 1


def test_pm1_report_contains_required_sections(tmp_path, monkeypatch) -> None:
    """The rendered draft report should include every required section heading."""

    agent, _, engine = _build_agent(tmp_path, monkeypatch)
    run_id = "run-5"
    model_id = "model-5"
    _seed_context(engine, run_id=run_id, model_id=model_id)
    message = _build_message(run_id=run_id, model_id=model_id)
    agent.call_llm = lambda **kwargs: _mock_llm_response()

    result = agent.process(message)

    required_sections = [
        "## Investment Thesis (Page 1)",
        "## Financial Summary Table",
        "## Business Model & Competitive Position",
        "## Earnings Review: Actual vs. Consensus",
        "## Three-Scenario Financial Model (Bear / Base / Bull)",
        "## WACC / Terminal Growth Sensitivity Table",
        "## Risk Factors",
        "## Appendix (DCF detail, peer comp table)",
        "Pipeline run ID: run-5 | Model ID: model-5",
    ]

    expected_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert f"# AAPL — BUY | Target: $212.34 | {expected_date}" in result.report_draft_md
    for section in required_sections:
        assert section in result.report_draft_md


def test_pm1_prompt_includes_style_guide() -> None:
    """The PM1 thesis prompt should include the shared style guide content."""

    environment = Environment(loader=FileSystemLoader(str(PROMPT_DIR)), autoescape=False)
    template = environment.get_template("pm1_thesis.j2")
    rendered = template.render(ticker="AAPL", rating="BUY", target_price=212.34, run_id="run-1", model_id="model-1")

    assert "delve" in rendered
    assert "Page 1 must answer only three questions" in rendered


def test_revision_prompt_references_issues() -> None:
    """The PM1 revision prompt should surface the issue list verbatim."""

    environment = Environment(loader=FileSystemLoader(str(PROMPT_DIR)), autoescape=False)
    template = environment.get_template("pm1_revision.j2")
    rendered = template.render(
        ticker="AAPL",
        rating="BUY",
        target_price=212.34,
        run_id="run-1",
        model_id="model-1",
        issues=["Wrong target price math", "Risk factor not quantified"],
        current_draft="Draft body",
        iteration=2,
    )

    assert "Wrong target price math" in rendered
    assert "Risk factor not quantified" in rendered


def test_all_prompts_render_without_error() -> None:
    """Every prompt template should render with a small but complete context."""

    context = {
        "fred": {"FEDFUNDS": 5.0, "DGS10": 4.2},
        "fomc_summary": "Rates held steady.",
        "trigger": SimpleNamespace(ticker="AAPL", trigger_type="manual"),
        "regime": "hiking",
        "overweights": ["Technology"],
        "sectors": {
            "Technology": {"primary_multiple": "EV/EBITDA", "metrics": ["revenue growth", "gross margin"]}
        },
        "primary_sector": "Technology",
        "orig_ticker": "AAPL",
        "candidates": [SimpleNamespace(ticker="MSFT", score=0.92)],
        "ticker": "AAPL",
        "rating": "BUY",
        "target_price": 212.34,
        "current_price": 180.0,
        "dcf_value": 205.0,
        "peer_multiple_value": 219.68,
        "metric_used": "EV/EBITDA",
        "run_id": "run-1",
        "model_id": "model-1",
        "current_draft": "Draft body",
        "iteration": 2,
        "issues": ["Wrong target price math", "Risk factor not quantified"],
    }

    prompt_files = sorted(path.relative_to(PROMPT_DIR).as_posix() for path in PROMPT_DIR.rglob("*.j2"))

    for template_name in prompt_files:
        rendered = load_prompt(template_name, **context)
        assert rendered.strip()


def test_rs1_prompt_contains_required_fields() -> None:
    """The RS1 macro prompt must surface the required output fields."""

    rendered = load_prompt(
        "rs1_macro.j2",
        fred={"FEDFUNDS": 5.0},
        fomc_summary="Rates held steady.",
        trigger=SimpleNamespace(ticker="AAPL", trigger_type="manual"),
    )

    assert "regime" in rendered
    assert "sector_overweights" in rendered
    assert "confidence" in rendered
    assert "reasoning" in rendered
