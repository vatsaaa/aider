"""Tests for the LLM routing layer."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text

from llm.claude_client import ClaudeClient
from llm.confidence import compute_confidence
from llm.ollama_client import OllamaClient
from llm.router import call_llm
from core.exceptions import OllamaUnavailableError, SpendLimitError


def _settings(db_url: str, limit: float = 10.0) -> SimpleNamespace:
    """Build a minimal settings object for router tests."""

    return SimpleNamespace(
        ANTHROPIC_API_KEY="test-key",
        OLLAMA_HOST="http://ollama.local",
        OLLAMA_MODEL="gemma4:e4b",
        AIDER_DATABASE_URL=db_url,
        DAILY_CLAUDE_SPEND_LIMIT_USD=limit,
        CONFIDENCE_THRESHOLD=0.75,
        CLAUDE_MODEL="claude-sonnet-4-20250514",
    )


def _prepare_llm_ledger(db_url: str) -> None:
    """Create the minimal llm_calls table required for the router tests."""

    engine = create_engine(db_url, future=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS llm_calls ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "run_id TEXT,"
                "agent TEXT,"
                "provider TEXT,"
                "model TEXT,"
                "prompt TEXT,"
                "response TEXT,"
                "confidence REAL,"
                "cost_usd REAL,"
                "input_tokens INTEGER,"
                "output_tokens INTEGER,"
                "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                ")"
            )
        )


def test_router_uses_ollama_for_rs1(tmp_path, monkeypatch):
    """The router should choose Ollama first for RS1 and stay off Claude."""

    db_path = tmp_path / "router.db"
    db_url = f"sqlite:///{db_path}"
    _prepare_llm_ledger(db_url)
    test_settings = _settings(db_url)

    ollama_called = {"value": False}

    def fake_ollama(self, system_prompt, user_prompt, response_schema=None, max_tokens=1000, model=None):
        ollama_called["value"] = True
        return {
            "regime": "bull",
            "confidence": 0.92,
            "sector_overweights": {"Technology": 0.4},
            "reasoning": "Macro backdrop is supportive.",
        }

    def fail_claude(self, *args, **kwargs):
        raise AssertionError("Claude should not be called for rs1_macro when Ollama is available")

    monkeypatch.setattr(OllamaClient, "generate", fake_ollama)
    monkeypatch.setattr(ClaudeClient, "complete", fail_claude)

    schema = {
        "type": "object",
        "required": ["regime", "confidence", "sector_overweights", "reasoning"],
        "properties": {
            "regime": {"type": "string"},
            "confidence": {"type": "number"},
            "sector_overweights": {"type": "object"},
            "reasoning": {"type": "string"},
        },
    }

    result = call_llm(
        agent_name="rs1_macro",
        system_prompt="system",
        user_prompt="user",
        response_schema=schema,
        settings=test_settings,
    )

    assert ollama_called["value"] is True
    assert result["regime"] == "bull"


def test_router_escalates_to_claude_on_low_confidence(tmp_path, monkeypatch):
    """A low-confidence Ollama result should trigger a Claude fallback."""

    db_path = tmp_path / "router.db"
    db_url = f"sqlite:///{db_path}"
    _prepare_llm_ledger(db_url)
    test_settings = _settings(db_url)

    calls = {"ollama": 0, "claude": 0}

    def fake_ollama(self, system_prompt, user_prompt, response_schema=None, max_tokens=1000, model=None):
        calls["ollama"] += 1
        return {
            "regime": "bull",
            "confidence": 0.4,
            "sector_overweights": {"Technology": 0.4},
            "reasoning": "Supportive backdrop but confidence is low.",
        }

    def fake_claude(self, system_prompt, user_prompt, response_schema=None, max_tokens=1000, model=None, log_call=True):
        calls["claude"] += 1
        return {
            "regime": "bull",
            "confidence": 0.94,
            "sector_overweights": {"Technology": 0.5},
            "reasoning": "Claude provides the final structured answer.",
        }

    monkeypatch.setattr(OllamaClient, "generate", fake_ollama)
    monkeypatch.setattr(ClaudeClient, "complete", fake_claude)

    schema = {
        "type": "object",
        "required": ["regime", "confidence", "sector_overweights", "reasoning"],
        "properties": {
            "regime": {"type": "string"},
            "confidence": {"type": "number"},
            "sector_overweights": {"type": "object"},
            "reasoning": {"type": "string"},
        },
    }

    result = call_llm(
        agent_name="rs1_macro",
        system_prompt="system",
        user_prompt="user",
        response_schema=schema,
        settings=test_settings,
    )

    assert calls["ollama"] == 1
    assert calls["claude"] == 1
    assert result["reasoning"] == "Claude provides the final structured answer."


def test_router_always_uses_claude_for_pm1(tmp_path, monkeypatch):
    """PM1 must route directly to Claude and skip Ollama entirely."""

    db_path = tmp_path / "router.db"
    db_url = f"sqlite:///{db_path}"
    _prepare_llm_ledger(db_url)
    test_settings = _settings(db_url)

    def fail_ollama(self, *args, **kwargs):
        raise AssertionError("Ollama should not be called for pm1_thesis")

    claude_called = {"value": False}

    def fake_claude(self, system_prompt, user_prompt, response_schema=None, max_tokens=1000, model=None, log_call=True):
        claude_called["value"] = True
        return {"response": "Claude handled the thesis stage."}

    monkeypatch.setattr(OllamaClient, "generate", fail_ollama)
    monkeypatch.setattr(ClaudeClient, "complete", fake_claude)

    result = call_llm(
        agent_name="pm1_thesis",
        system_prompt="system",
        user_prompt="user",
        response_schema={"type": "object", "required": ["response"]},
        settings=test_settings,
    )

    assert claude_called["value"] is True
    assert result == {"response": "Claude handled the thesis stage."}


def test_spend_limit_blocks_claude_call(tmp_path, monkeypatch):
    """Claude should raise before network use when today's spend hits the limit."""

    db_path = tmp_path / "router.db"
    db_url = f"sqlite:///{db_path}"
    _prepare_llm_ledger(db_url)
    engine = create_engine(db_url, future=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO llm_calls (run_id, agent, provider, model, prompt, response, confidence, cost_usd, created_at) "
                "VALUES ('run-1', 'pm1_thesis', 'anthropic', 'claude-sonnet-4-20250514', 'prompt', 'response', 1.0, 10.0, CURRENT_TIMESTAMP)"
            )
        )

    test_settings = _settings(db_url, limit=10.0)

    class FailAnthropic:
        def __init__(self, *args, **kwargs):
            raise AssertionError("Anthropic should not be reached once the spend limit is hit")

    monkeypatch.setattr("llm.claude_client.Anthropic", FailAnthropic)

    with pytest.raises(SpendLimitError):
        call_llm(
            agent_name="pm1_thesis",
            system_prompt="system",
            user_prompt="user",
            response_schema={"type": "object", "required": ["response"]},
            settings=test_settings,
        )


def test_confidence_missing_field_penalty():
    """Missing one required field from a three-field schema should cost 0.15."""

    score = compute_confidence(
        {"alpha": 1, "beta": 2},
        {
            "type": "object",
            "required": ["alpha", "beta", "gamma"],
            "properties": {"alpha": {}, "beta": {}, "gamma": {}},
        },
    )

    assert score == pytest.approx(0.85)


def test_ollama_unavailable_escalates_to_claude(tmp_path, monkeypatch):
    """Transport failure in Ollama should fall back to Claude."""

    db_path = tmp_path / "router.db"
    db_url = f"sqlite:///{db_path}"
    _prepare_llm_ledger(db_url)
    test_settings = _settings(db_url)

    def raise_unavailable(self, *args, **kwargs):
        raise OllamaUnavailableError("Ollama unavailable")

    claude_called = {"value": False}

    def fake_claude(self, system_prompt, user_prompt, response_schema=None, max_tokens=1000, model=None, log_call=True):
        claude_called["value"] = True
        return {
            "regime": "neutral",
            "confidence": 0.9,
            "sector_overweights": {},
            "reasoning": "Claude handled the fallback path.",
        }

    monkeypatch.setattr(OllamaClient, "generate", raise_unavailable)
    monkeypatch.setattr(ClaudeClient, "complete", fake_claude)

    result = call_llm(
        agent_name="rs1_macro",
        system_prompt="system",
        user_prompt="user",
        response_schema={
            "type": "object",
            "required": ["regime", "confidence", "sector_overweights", "reasoning"],
            "properties": {
                "regime": {"type": "string"},
                "confidence": {"type": "number"},
                "sector_overweights": {"type": "object"},
                "reasoning": {"type": "string"},
            },
        },
        settings=test_settings,
    )

    assert claude_called["value"] is True
    assert result["regime"] == "neutral"

def test_routed_claude_call_records_actual_cost(tmp_path, monkeypatch):
    """Routed Claude calls must log their token-based cost so the spend limit can see it."""

    db_url = f"sqlite:///{tmp_path / 'router.db'}"
    _prepare_llm_ledger(db_url)

    class FakeAnthropic:
        def __init__(self, *args, **kwargs):
            self.messages = SimpleNamespace(create=lambda **_: SimpleNamespace(
                content=[SimpleNamespace(text='{"response": "ok"}')],
                usage=SimpleNamespace(input_tokens=1_000_000, output_tokens=0),
            ))

    monkeypatch.setattr("llm.claude_client.Anthropic", FakeAnthropic)

    call_llm(
        agent_name="pm1_thesis",
        system_prompt="system",
        user_prompt="user",
        response_schema={"type": "object", "required": ["response"]},
        settings=_settings(db_url),
    )

    with create_engine(db_url, future=True).connect() as connection:
        total = connection.execute(text("SELECT SUM(cost_usd) FROM llm_calls WHERE provider = 'anthropic'")).scalar()
    assert total == pytest.approx(3.0)
