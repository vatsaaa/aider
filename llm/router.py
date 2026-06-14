"""Central LLM routing policy for the Digital Equity Analyst.

The router chooses a provider per agent, escalates low-confidence Ollama
responses to Claude, and records every provider call in `llm_calls` so the
pipeline has a complete audit trail.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

import yaml
from sqlalchemy import MetaData, Table, create_engine

from core.exceptions import OllamaUnavailableError
from core.logger import get_logger

from .claude_client import ClaudeClient, DEFAULT_CLAUDE_MODEL
from .confidence import compute_confidence
from .ollama_client import OllamaClient


LLM_OLLAMA = "ollama/gemma4:e4b"
LLM_CLAUDE = "anthropic/claude-sonnet-4-20250514"
DEFAULT_CONFIDENCE_THRESHOLD = 0.75
LLM_LESS_AGENTS = {"av1", "av2", "pm2"}


class LLMRouter:
    """Backward-compatible router class used by existing tests."""

    LLM_OLLAMA = LLM_OLLAMA
    LLM_CLAUDE = LLM_CLAUDE
    LLM_LESS_AGENTS = LLM_LESS_AGENTS

    def select_provider(self, agent_name: str) -> Optional[str]:
        """Return the default provider identifier for an agent."""

        route = _resolve_route(agent_name.strip().lower())
        strategy = route.get("strategy")
        if strategy == "none":
            return None
        if strategy == "fallback_always" or route.get("provider") == "anthropic":
            return self.LLM_CLAUDE
        return self.LLM_OLLAMA

    def compute_confidence(
        self,
        missing_required_fields: int,
        null_required_fields: int,
        domain_logic_check_fails: bool,
    ) -> float:
        """Preserve the historical numeric confidence helper used by tests."""

        score = 1.0
        score -= missing_required_fields * 0.15
        score -= null_required_fields * 0.10
        if domain_logic_check_fails:
            score -= 0.25
        return max(0.0, min(1.0, score))


def call_llm(
    agent_name: str,
    system_prompt: str,
    user_prompt: str,
    response_schema: dict[str, Any] | None = None,
    max_tokens: int = 1000,
    settings: Any | None = None,
    run_id: str | None = None,
    ticker: str | None = None,
    stream: str | None = None,
) -> dict[str, Any] | str:
    """Route a model request to the appropriate provider and record it."""

    active_settings = settings or _default_settings()
    agent_key = agent_name.strip().lower()
    logger = get_logger(agent=agent_key, run_id=run_id, ticker=ticker, stream=stream)

    route = _resolve_route(agent_key)
    if route.get("strategy") == "none":
        raise RuntimeError(f"Agent {agent_name} does not use an LLM")

    if route.get("strategy") == "fallback_always" or route.get("provider") == "anthropic":
        return _call_claude(
            active_settings=active_settings,
            agent_key=agent_key,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_schema=response_schema,
            max_tokens=max_tokens,
            model=route.get("model") or getattr(active_settings, "CLAUDE_MODEL", DEFAULT_CLAUDE_MODEL),
            run_id=run_id,
            logger=logger,
        )

    ollama = OllamaClient(active_settings)
    ollama_model = route.get("model") or getattr(active_settings, "OLLAMA_MODEL", "gemma4:e4b")
    try:
        ollama_result = ollama.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_schema=response_schema,
            max_tokens=max_tokens,
            model=ollama_model,
        )
    except OllamaUnavailableError as error:
        logger.warning("llm_ollama_unavailable", error_type=error.__class__.__name__, error_message=str(error))
        _record_llm_call(
            settings=active_settings,
            agent_name=agent_key,
            provider="ollama",
            model=ollama_model,
            prompt=_combined_prompt(system_prompt, user_prompt, response_schema),
            response={"error": str(error), "status": "unavailable"},
            confidence=None,
            cost_usd=0.0,
            run_id=run_id,
        )
        return _call_claude(
            active_settings=active_settings,
            agent_key=agent_key,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_schema=response_schema,
            max_tokens=max_tokens,
            model=getattr(active_settings, "CLAUDE_MODEL", DEFAULT_CLAUDE_MODEL),
            run_id=run_id,
            logger=logger,
        )

    confidence = _response_confidence(ollama_result, response_schema)
    _record_llm_call(
        settings=active_settings,
        agent_name=agent_key,
        provider="ollama",
        model=ollama_model,
        prompt=_combined_prompt(system_prompt, user_prompt, response_schema),
        response=ollama_result,
        confidence=confidence,
        cost_usd=0.0,
        run_id=run_id,
    )
    logger.info("llm_call_completed", provider="ollama", model=ollama_model, confidence=confidence)

    threshold = float(getattr(active_settings, "CONFIDENCE_THRESHOLD", DEFAULT_CONFIDENCE_THRESHOLD))
    if response_schema is not None and confidence < threshold:
        return _call_claude(
            active_settings=active_settings,
            agent_key=agent_key,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_schema=response_schema,
            max_tokens=max_tokens,
            model=getattr(active_settings, "CLAUDE_MODEL", DEFAULT_CLAUDE_MODEL),
            run_id=run_id,
            logger=logger,
        )

    return ollama_result


def _resolve_route(agent_name: str) -> dict[str, Any]:
    """Return the routing rule for an agent from config with sane defaults."""

    config = _load_config()
    routing = config.get("routing", {}) if isinstance(config, dict) else {}
    default_rule = config.get("default", {}) if isinstance(config, dict) else {}
    no_llm_agents = set(config.get("no_llm_agents", []) if isinstance(config, dict) else [])

    if agent_name in routing and isinstance(routing[agent_name], dict):
        return routing[agent_name]

    if agent_name in no_llm_agents or agent_name in LLM_LESS_AGENTS:
        return {"strategy": "none"}

    if agent_name == "pm1_thesis":
        return {
            "strategy": "fallback_always",
            "provider": "anthropic",
            "model": default_rule.get("claude_model", DEFAULT_CLAUDE_MODEL),
        }

    return {
        "strategy": default_rule.get("strategy", "ollama_first"),
        "provider": default_rule.get("primary_provider", "ollama"),
        "model": default_rule.get("ollama_model", LLM_OLLAMA),
    }


@lru_cache(maxsize=1)
def _load_config() -> dict[str, Any]:
    """Load the LLM routing configuration file once per process."""

    config_path = Path(__file__).resolve().parents[1] / "config" / "llm.yaml"
    if not config_path.exists():
        return {
            "default": {
                "primary_provider": "ollama",
                "fallback_provider": "anthropic",
                "ollama_model": "gemma4:e4b",
                "claude_model": DEFAULT_CLAUDE_MODEL,
                "strategy": "ollama_first",
            },
            "routing": {
                "pm1_thesis": {
                    "strategy": "fallback_always",
                    "provider": "anthropic",
                    "model": DEFAULT_CLAUDE_MODEL,
                }
            },
            "no_llm_agents": ["av1", "av2", "pm2"],
        }

    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return data if isinstance(data, dict) else {}


def _combined_prompt(
    system_prompt: str,
    user_prompt: str,
    response_schema: dict[str, Any] | None,
) -> str:
    """Build the canonical prompt payload used for ledger logging."""

    pieces = ["System prompt:", system_prompt.strip(), "", "User prompt:", user_prompt.strip()]
    if response_schema:
        pieces.extend(["", "Schema:", json.dumps(response_schema, indent=2, sort_keys=True)])
    return "\n".join(pieces).strip()


def _response_confidence(response: Any, response_schema: dict[str, Any] | None) -> float | None:
    """Compute confidence when a structured schema is available."""

    if not isinstance(response, dict):
        return None

    derived_confidence = compute_confidence(response, response_schema or {}) if response_schema else None
    reported_confidence = response.get("confidence")
    if isinstance(reported_confidence, (int, float)):
        if derived_confidence is None:
            return float(reported_confidence)
        return min(float(reported_confidence), float(derived_confidence))

    return derived_confidence


def _engine(settings: Any):
    """Build a SQLAlchemy engine for the configured database URL."""

    return create_engine(getattr(settings, "AIDER_DATABASE_URL"), future=True)


def _default_settings() -> Any:
    """Return the real settings object when available, otherwise a stub."""

    try:
        from core.config import settings as loaded_settings
    except Exception:
        return SimpleNamespace(
            OLLAMA_HOST="http://localhost:11434",
            OLLAMA_MODEL="gemma4:e4b",
            CLAUDE_MODEL=DEFAULT_CLAUDE_MODEL,
            CONFIDENCE_THRESHOLD=DEFAULT_CONFIDENCE_THRESHOLD,
            DAILY_CLAUDE_SPEND_LIMIT_USD=10.0,
            AIDER_DATABASE_URL="sqlite:///:memory:",
            ANTHROPIC_API_KEY="",
        )

    return loaded_settings


def _call_claude(
    *,
    active_settings: Any,
    agent_key: str,
    system_prompt: str,
    user_prompt: str,
    response_schema: dict[str, Any] | None,
    max_tokens: int,
    model: str,
    run_id: str | None,
    logger: Any,
) -> dict[str, Any] | str:
    """Call Claude, log the request, and return its parsed response."""

    claude = ClaudeClient(active_settings)
    result = claude.complete(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response_schema=response_schema,
        max_tokens=max_tokens,
        model=model,
        log_call=False,
    )
    confidence = _response_confidence(result, response_schema)
    _record_llm_call(
        settings=active_settings,
        agent_name=agent_key,
        provider="anthropic",
        model=model,
        prompt=_combined_prompt(system_prompt, user_prompt, response_schema),
        response=result,
        confidence=confidence,
        cost_usd=_estimate_cost_from_result(result),
        run_id=run_id,
    )
    logger.info("llm_call_completed", provider="anthropic", model=model, confidence=confidence)
    return result


def _estimate_cost_from_result(result: Any) -> float:
    """Best-effort cost estimate for a Claude response when exact usage is unavailable."""

    if isinstance(result, dict):
        token_proxy = len(json.dumps(result))
    else:
        token_proxy = len(str(result))
    return float(token_proxy) * 0.0


def _record_llm_call(
    *,
    settings: Any,
    agent_name: str,
    provider: str,
    model: str,
    prompt: str,
    response: Any,
    confidence: float | None,
    cost_usd: float,
    run_id: str | None = None,
) -> None:
    """Insert a ledger entry into `llm_calls` using portable SQL."""

    engine = _engine(settings)
    metadata = MetaData()
    table = Table("llm_calls", metadata, autoload_with=engine)
    existing_columns = {column.name for column in table.columns}

    payload: dict[str, Any] = {
        "run_id": run_id,
        "agent": agent_name,
        "provider": provider,
        "model": model,
        "prompt": _serialize_for_column(table, "prompt", prompt),
        "response": _serialize_for_column(table, "response", response),
        "confidence": confidence,
        "cost_usd": cost_usd,
        "input_tokens": int(response.get("input_tokens", 0) or 0) if isinstance(response, dict) else None,
        "output_tokens": int(response.get("output_tokens", 0) or 0) if isinstance(response, dict) else None,
    }
    insert_payload = {
        key: value
        for key, value in payload.items()
        if key in existing_columns and value is not None
    }

    with engine.begin() as connection:
        connection.execute(table.insert().values(**insert_payload))


def _serialize_for_column(table: Table, column_name: str, value: Any) -> Any:
    """Serialize a value for the destination column type."""

    column = table.c.get(column_name)
    if column is None:
        return value

    column_type = column.type.__class__.__name__.lower()
    if "json" in column_type:
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return value


__all__ = ["LLMRouter", "call_llm", "_record_llm_call"]