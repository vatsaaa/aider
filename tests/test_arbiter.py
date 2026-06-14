"""Unit tests for the Arbiter agent."""

from __future__ import annotations

import time
from types import SimpleNamespace

from core.bus import InMemoryBus, Message
from critics.arbiter import Arbiter


def _build_arbiter():
    bus = InMemoryBus()
    settings = SimpleNamespace(MAX_REVISION_ITERATIONS=3)
    agent = Arbiter(bus=bus, db=None, settings=settings)
    return agent, bus


def _make_payload(critic: str, verdict: str, issues: list[str], iteration: int, run_id: str):
    return {"critic": critic, "verdict": verdict, "issues": issues, "iteration": iteration, "pipeline_run_id": run_id}


def test_arbiter_waits_for_all_three_verdicts():
    agent, bus = _build_arbiter()
    run_id = "run-test-1"

    m1 = Message(id="1", stream="critic:verdict:input", data={"payload": _make_payload("quant", "PASS", [], 1, run_id), "pipeline_run_id": run_id}, pipeline_run_id=run_id, ticker="AAPL", trigger_type="manual", timestamp="", payload=_make_payload("quant", "PASS", [], 1, run_id), metadata={})
    m2 = Message(id="2", stream="critic:verdict:input", data={"payload": _make_payload("logic", "PASS", [], 1, run_id), "pipeline_run_id": run_id}, pipeline_run_id=run_id, ticker="AAPL", trigger_type="manual", timestamp="", payload=_make_payload("logic", "PASS", [], 1, run_id), metadata={})

    agent.process(m1)
    agent.process(m2)

    assert bus.get_stream_length("critique:verdict") == 0
    assert bus.get_stream_length("critic:revision:input") == 0


def test_arbiter_all_pass_approves():
    agent, bus = _build_arbiter()
    run_id = "run-test-2"

    msgs = [
        Message(id="1", stream="critic:verdict:input", data={"payload": _make_payload("quant", "PASS", [], 1, run_id), "pipeline_run_id": run_id}, pipeline_run_id=run_id, ticker="AAPL", trigger_type="manual", timestamp="", payload=_make_payload("quant", "PASS", [], 1, run_id), metadata={}),
        Message(id="2", stream="critic:verdict:input", data={"payload": _make_payload("logic", "PASS", [], 1, run_id), "pipeline_run_id": run_id}, pipeline_run_id=run_id, ticker="AAPL", trigger_type="manual", timestamp="", payload=_make_payload("logic", "PASS", [], 1, run_id), metadata={}),
        Message(id="3", stream="critic:verdict:input", data={"payload": _make_payload("data", "PASS", [], 1, run_id), "pipeline_run_id": run_id}, pipeline_run_id=run_id, ticker="AAPL", trigger_type="manual", timestamp="", payload=_make_payload("data", "PASS", [], 1, run_id), metadata={}),
    ]

    for m in msgs:
        agent.process(m)

    assert bus.get_stream_length("critique:verdict") == 1
    out = bus.read("critique:verdict", count=1)[0]["message"]["payload"]
    assert out["verdict"] == "PASS"


def test_arbiter_one_fatal_rejects():
    agent, bus = _build_arbiter()
    run_id = "run-test-3"

    msgs = [
        Message(id="1", stream="critic:verdict:input", data={"payload": _make_payload("quant", "PASS", [], 1, run_id), "pipeline_run_id": run_id}, pipeline_run_id=run_id, ticker="AAPL", trigger_type="manual", timestamp="", payload=_make_payload("quant", "PASS", [], 1, run_id), metadata={}),
        Message(id="2", stream="critic:verdict:input", data={"payload": _make_payload("logic", "PASS", [], 1, run_id), "pipeline_run_id": run_id}, pipeline_run_id=run_id, ticker="AAPL", trigger_type="manual", timestamp="", payload=_make_payload("logic", "PASS", [], 1, run_id), metadata={}),
        Message(id="3", stream="critic:verdict:input", data={"payload": _make_payload("data", "FATAL", ["mnpi_phrase_detected"], 1, run_id), "pipeline_run_id": run_id}, pipeline_run_id=run_id, ticker="AAPL", trigger_type="manual", timestamp="", payload=_make_payload("data", "FATAL", ["mnpi_phrase_detected"], 1, run_id), metadata={}),
    ]

    for m in msgs:
        agent.process(m)

    assert bus.get_stream_length("critic:revision:input") == 1
    out = bus.read("critic:revision:input", count=1)[0]["message"]["payload"]
    assert out["verdict"] == "FATAL"
    assert "mnpi_phrase_detected" in out["issues"]


def test_arbiter_all_warn_approves_with_advisory():
    agent, bus = _build_arbiter()
    run_id = "run-test-4"

    msgs = [
        Message(id="1", stream="critic:verdict:input", data={"payload": _make_payload("quant", "WARN", ["minor_calc_issue"], 1, run_id), "pipeline_run_id": run_id}, pipeline_run_id=run_id, ticker="AAPL", trigger_type="manual", timestamp="", payload=_make_payload("quant", "WARN", ["minor_calc_issue"], 1, run_id), metadata={}),
        Message(id="2", stream="critic:verdict:input", data={"payload": _make_payload("logic", "WARN", ["hedging_language"], 1, run_id), "pipeline_run_id": run_id}, pipeline_run_id=run_id, ticker="AAPL", trigger_type="manual", timestamp="", payload=_make_payload("logic", "WARN", ["hedging_language"], 1, run_id), metadata={}),
        Message(id="3", stream="critic:verdict:input", data={"payload": _make_payload("data", "WARN", ["rounding_differences"], 1, run_id), "pipeline_run_id": run_id}, pipeline_run_id=run_id, ticker="AAPL", trigger_type="manual", timestamp="", payload=_make_payload("data", "WARN", ["rounding_differences"], 1, run_id), metadata={}),
    ]

    for m in msgs:
        agent.process(m)

    assert bus.get_stream_length("critique:verdict") == 1
    out = bus.read("critique:verdict", count=1)[0]["message"]["payload"]
    assert out["verdict"] == "PASS"
    # advisory issues should include all warn issues
    assert set(out["issues"]) == {"minor_calc_issue", "hedging_language", "rounding_differences"}


def test_arbiter_max_iterations_sends_to_dlq():
    agent, bus = _build_arbiter()
    run_id = "run-test-5"

    msgs = [
        Message(id="1", stream="critic:verdict:input", data={"payload": _make_payload("quant", "FATAL", ["bad_math"], 3, run_id), "pipeline_run_id": run_id}, pipeline_run_id=run_id, ticker="AAPL", trigger_type="manual", timestamp="", payload=_make_payload("quant", "FATAL", ["bad_math"], 3, run_id), metadata={}),
        Message(id="2", stream="critic:verdict:input", data={"payload": _make_payload("logic", "PASS", [], 3, run_id), "pipeline_run_id": run_id}, pipeline_run_id=run_id, ticker="AAPL", trigger_type="manual", timestamp="", payload=_make_payload("logic", "PASS", [], 3, run_id), metadata={}),
        Message(id="3", stream="critic:verdict:input", data={"payload": _make_payload("data", "PASS", [], 3, run_id), "pipeline_run_id": run_id}, pipeline_run_id=run_id, ticker="AAPL", trigger_type="manual", timestamp="", payload=_make_payload("data", "PASS", [], 3, run_id), metadata={}),
    ]

    for m in msgs:
        agent.process(m)

    # DLQ should have one entry
    assert bus.get_stream_length("dlq:failed") == 1
    # no revision should be published
    assert bus.get_stream_length("critic:revision:input") == 0


def test_arbiter_redis_hash_expires_after_1hr():
    agent, bus = _build_arbiter()
    run_id = "run-test-6"

    m1 = Message(id="1", stream="critic:verdict:input", data={"payload": _make_payload("quant", "PASS", [], 1, run_id), "pipeline_run_id": run_id}, pipeline_run_id=run_id, ticker="AAPL", trigger_type="manual", timestamp="", payload=_make_payload("quant", "PASS", [], 1, run_id), metadata={})

    agent.process(m1)

    ttl = agent.get_state_ttl(run_id)
    assert ttl is not None
    assert ttl <= 3600


def test_arbiter_run_publishes_only_once_per_decision(monkeypatch):
    agent, bus = _build_arbiter()
    run_id = "run-test-7"

    messages = [
        Message(id="1", stream="critic:verdict:input", data={"payload": _make_payload("quant", "PASS", [], 1, run_id), "pipeline_run_id": run_id}, pipeline_run_id=run_id, ticker="AAPL", trigger_type="manual", timestamp="", payload=_make_payload("quant", "PASS", [], 1, run_id), metadata={}),
        Message(id="2", stream="critic:verdict:input", data={"payload": _make_payload("logic", "PASS", [], 1, run_id), "pipeline_run_id": run_id}, pipeline_run_id=run_id, ticker="AAPL", trigger_type="manual", timestamp="", payload=_make_payload("logic", "PASS", [], 1, run_id), metadata={}),
        Message(id="3", stream="critic:verdict:input", data={"payload": _make_payload("data", "PASS", [], 1, run_id), "pipeline_run_id": run_id}, pipeline_run_id=run_id, ticker="AAPL", trigger_type="manual", timestamp="", payload=_make_payload("data", "PASS", [], 1, run_id), metadata={}),
    ]

    calls = {"count": 0}

    def consume_once(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return messages
        raise StopIteration

    monkeypatch.setattr(bus, "consume", consume_once)

    agent.run()

    assert bus.get_stream_length("critique:verdict") == 1
