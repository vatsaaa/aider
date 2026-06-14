"""Unit tests for the three critics: quant, logic and data."""

from __future__ import annotations

from types import SimpleNamespace
from core.bus import InMemoryBus, Message

from critics.quant_critic import QuantCritic
from critics.logic_critic import LogicCritic
from critics.data_critic import DataCritic


def _build_agent(agent_cls):
    bus = InMemoryBus()
    settings = SimpleNamespace(MAX_REVISION_ITERATIONS=3)
    agent = agent_cls(bus=bus, db=None, settings=settings)
    return agent, bus


def test_quant_critic_fatal_on_wrong_target_price():
    agent, bus = _build_agent(QuantCritic)
    run_id = "run-quant-1"
    # create a message where stated target is 30% above model
    message = Message(
        id="m1",
        stream="critic:quant:input",
        data={"payload": {"stated_target_price": 130.0, "model_target_price": 100.0, "iteration": 1}, "pipeline_run_id": run_id},
        pipeline_run_id=run_id,
        ticker="AAPL",
        trigger_type="manual",
        timestamp="",
        payload={"stated_target_price": 130.0, "model_target_price": 100.0, "iteration": 1},
        metadata={"retry_count": 0},
    )

    # Mock LLM via monkeypatch-style replacement
    agent.call_llm = lambda **kwargs: {"verdict": "FATAL", "issues": ["target_price_mismatch"], "iteration": 1, "pipeline_run_id": run_id}

    result = agent.process(message)
    agent.publish_result(result, message)

    assert result.verdict == "FATAL"
    assert bus.get_stream_length("critic:verdict:input") == 1


def test_quant_critic_pass_on_correct_math():
    agent, bus = _build_agent(QuantCritic)
    run_id = "run-quant-2"
    message = Message(
        id="m2",
        stream="critic:quant:input",
        data={"payload": {"stated_target_price": 105.0, "model_target_price": 100.0, "iteration": 1}, "pipeline_run_id": run_id},
        pipeline_run_id=run_id,
        ticker="AAPL",
        trigger_type="manual",
        timestamp="",
        payload={"stated_target_price": 105.0, "model_target_price": 100.0, "iteration": 1},
        metadata={"retry_count": 0},
    )

    agent.call_llm = lambda **kwargs: {"verdict": "PASS", "issues": [], "iteration": 1, "pipeline_run_id": run_id}

    result = agent.process(message)
    agent.publish_result(result, message)

    assert result.verdict == "PASS"


def test_logic_critic_fatal_on_unquantified_risk():
    agent, bus = _build_agent(LogicCritic)
    run_id = "run-logic-1"
    draft = "## Investment Thesis (Page 1)\nSome text.\n## Risk Factors\nmacro deterioration without specifics"
    message = Message(
        id="m3",
        stream="critic:logic:input",
        data={"payload": {"report_draft_md": draft, "iteration": 1}, "pipeline_run_id": run_id},
        pipeline_run_id=run_id,
        ticker="AAPL",
        trigger_type="manual",
        timestamp="",
        payload={"report_draft_md": draft, "iteration": 1},
        metadata={"retry_count": 0},
    )

    agent.call_llm = lambda **kwargs: {"verdict": "FATAL", "issues": ["risk_factors_not_quantified"], "iteration": 1, "pipeline_run_id": run_id}

    result = agent.process(message)
    agent.publish_result(result, message)

    assert result.verdict == "FATAL"


def test_logic_critic_pass_on_quantified_risks():
    agent, bus = _build_agent(LogicCritic)
    run_id = "run-logic-2"
    draft = "## Investment Thesis (Page 1) by 2027\nSome text.\n## Risk Factors\nA 75bps rate hike compresses NIM 30bps, reducing EPS 18%"
    message = Message(
        id="m4",
        stream="critic:logic:input",
        data={"payload": {"report_draft_md": draft, "iteration": 1}, "pipeline_run_id": run_id},
        pipeline_run_id=run_id,
        ticker="AAPL",
        trigger_type="manual",
        timestamp="",
        payload={"report_draft_md": draft, "iteration": 1},
        metadata={"retry_count": 0},
    )

    agent.call_llm = lambda **kwargs: {"verdict": "PASS", "issues": [], "iteration": 1, "pipeline_run_id": run_id}

    result = agent.process(message)
    agent.publish_result(result, message)

    assert result.verdict == "PASS"


def test_data_critic_fatal_on_mnpi_phrase():
    agent, bus = _build_agent(DataCritic)
    run_id = "run-data-1"
    draft = "## Investment Thesis (Page 1)\nWe expect results before announcement that will surprise markets."
    message = Message(
        id="m5",
        stream="critic:data:input",
        data={"payload": {"report_draft_md": draft, "iteration": 1}, "pipeline_run_id": run_id},
        pipeline_run_id=run_id,
        ticker="AAPL",
        trigger_type="manual",
        timestamp="",
        payload={"report_draft_md": draft, "iteration": 1},
        metadata={"retry_count": 0},
    )

    agent.call_llm = lambda **kwargs: {"verdict": "FATAL", "issues": ["mnpi_phrase_detected:before announcement"], "iteration": 1, "pipeline_run_id": run_id}

    result = agent.process(message)
    agent.publish_result(result, message)

    assert result.verdict == "FATAL"


def test_data_critic_fatal_on_figure_mismatch():
    agent, bus = _build_agent(DataCritic)
    run_id = "run-data-2"
    message = Message(
        id="m6",
        stream="critic:data:input",
        data={"payload": {"figures": {"revenue": 50000000000}, "model_figures": {"revenue": 42000000000}, "iteration": 1}, "pipeline_run_id": run_id},
        pipeline_run_id=run_id,
        ticker="AAPL",
        trigger_type="manual",
        timestamp="",
        payload={"figures": {"revenue": 50000000000}, "model_figures": {"revenue": 42000000000}, "iteration": 1},
        metadata={"retry_count": 0},
    )

    agent.call_llm = lambda **kwargs: {"verdict": "FATAL", "issues": ["figure_mismatch:revenue"], "iteration": 1, "pipeline_run_id": run_id}

    result = agent.process(message)
    agent.publish_result(result, message)

    assert result.verdict == "FATAL"


def test_quant_critic_deterministic_overrides_llm_pass():
    agent, bus = _build_agent(QuantCritic)
    run_id = "run-quant-3"
    message = Message(
        id="m7",
        stream="critic:quant:input",
        data={"payload": {"stated_target_price": 150.0, "model_target_price": 100.0, "iteration": 1}, "pipeline_run_id": run_id},
        pipeline_run_id=run_id,
        ticker="AAPL",
        trigger_type="manual",
        timestamp="",
        payload={"stated_target_price": 150.0, "model_target_price": 100.0, "iteration": 1},
        metadata={},
    )

    # Even if LLM returns PASS, the 50% deviation should make the verdict FATAL deterministically
    agent.call_llm = lambda **kwargs: {"verdict": "PASS", "issues": [], "iteration": 1, "pipeline_run_id": run_id}

    result = agent.process(message)
    assert result.verdict == "FATAL"
    assert any("target_price_mismatch" in issue for issue in result.issues)


def test_logic_critic_deterministic_overrides_llm_pass():
    agent, bus = _build_agent(LogicCritic)
    run_id = "run-logic-3"
    draft = "## Investment Thesis (Page 1) by 2027\nSome text.\n## Risk Factors\nmacro deterioration without specifics"
    message = Message(
        id="m8",
        stream="critic:logic:input",
        data={"payload": {"report_draft_md": draft, "iteration": 1}, "pipeline_run_id": run_id},
        pipeline_run_id=run_id,
        ticker="AAPL",
        trigger_type="manual",
        timestamp="",
        payload={"report_draft_md": draft, "iteration": 1},
        metadata={},
    )

    # Even if LLM returns PASS, unquantified risks should make the verdict FATAL deterministically
    agent.call_llm = lambda **kwargs: {"verdict": "PASS", "issues": [], "iteration": 1, "pipeline_run_id": run_id}

    result = agent.process(message)
    assert result.verdict == "FATAL"
    assert "risk_factors_not_quantified" in result.issues


def test_data_critic_deterministic_overrides_llm_pass():
    agent, bus = _build_agent(DataCritic)
    run_id = "run-data-3"
    draft = "## Investment Thesis (Page 1)\nWe expect results before announcement that will surprise markets."
    message = Message(
        id="m9",
        stream="critic:data:input",
        data={"payload": {"report_draft_md": draft, "iteration": 1}, "pipeline_run_id": run_id},
        pipeline_run_id=run_id,
        ticker="AAPL",
        trigger_type="manual",
        timestamp="",
        payload={"report_draft_md": draft, "iteration": 1},
        metadata={},
    )

    # Even if LLM returns PASS, MNPI phrase should make the verdict FATAL deterministically
    agent.call_llm = lambda **kwargs: {"verdict": "PASS", "issues": [], "iteration": 1, "pipeline_run_id": run_id}

    result = agent.process(message)
    assert result.verdict == "FATAL"
    assert any("mnpi_phrase_detected" in issue for issue in result.issues)

