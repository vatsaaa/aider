"""Transport client for Claude completions.

This module enforces the daily Claude spend guardrail, calls Anthropic's SDK,
and writes a ledger row for every completion so the router can trace cost and
usage without depending on provider internals.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from sqlalchemy import MetaData, Table, create_engine, inspect, text

from core.exceptions import SpendLimitError

try:  # pragma: no cover - exercised indirectly in environments with the SDK installed
    from anthropic import Anthropic
except ModuleNotFoundError:  # pragma: no cover - keeps unit tests importable without the SDK
    class Anthropic:  # type: ignore[no-redef]
        """Fallback stub that surfaces a clear error if Claude is used without the SDK."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            raise ModuleNotFoundError("anthropic is not installed")


DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-20250514"


class ClaudeClient:
    """Call Claude while enforcing the daily spend guardrail."""

    def __init__(self, settings: Any) -> None:
        """Store settings used for spend checks and request construction."""

        self.settings = settings
        self.last_cost_usd = 0.0

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: Mapping[str, Any] | None = None,
        max_tokens: int = 1000,
        model: str | None = None,
        log_call: bool = True,
    ) -> dict[str, Any] | str:
        """Call Claude and optionally write the call record to the DB ledger."""

        self._ensure_spend_within_limit()

        claude_model = model or getattr(self.settings, "CLAUDE_MODEL", DEFAULT_CLAUDE_MODEL)
        prompt = self._compose_prompt(system_prompt, user_prompt, response_schema)
        client = Anthropic(api_key=getattr(self.settings, "ANTHROPIC_API_KEY", ""))
        response = client.messages.create(
            model=claude_model,
            max_tokens=max_tokens,
            temperature=0.1,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
        )

        self.last_cost_usd = self._estimate_cost(response)
        text_output = self._extract_text(response)
        try:
            parsed_output: dict[str, Any] | str = json.loads(text_output)
        except json.JSONDecodeError:
            parsed_output = text_output

        if log_call:
            confidence = None
            if isinstance(parsed_output, dict) and response_schema:
                from .confidence import compute_confidence

                confidence = compute_confidence(parsed_output, dict(response_schema))

            self._record_call(
                agent_name="claude_client",
                provider="anthropic",
                model=claude_model,
                prompt=prompt,
                response=parsed_output,
                confidence=confidence,
                cost_usd=self.last_cost_usd,
                input_tokens=self._extract_token_count(response, "input_tokens"),
                output_tokens=self._extract_token_count(response, "output_tokens"),
            )

        return parsed_output

    def _ensure_spend_within_limit(self) -> None:
        """Raise when today's Claude spend is at or above the configured limit."""

        current_spend = self._today_spend_usd()
        limit = float(getattr(self.settings, "DAILY_CLAUDE_SPEND_LIMIT_USD", 10.0))
        if current_spend >= limit:
            raise SpendLimitError(
                f"Claude spend limit reached: {current_spend:.2f} USD (limit {limit:.2f} USD)"
            )

    def _today_spend_usd(self) -> float:
        """Read today's spend from the underlying ledger of Claude calls."""

        engine = self._engine_for_settings()
        query = self._daily_spend_query(engine)
        with engine.connect() as connection:
            result = connection.execute(query).first()
        if result is None:
            return 0.0
        value = result[0]
        return float(value or 0.0)

    @lru_cache(maxsize=8)
    def _engine_for_settings(self):
        """Build a cached SQLAlchemy engine for the configured database URL."""

        database_url = getattr(self.settings, "AIDER_DATABASE_URL", None) or getattr(self.settings, "DATABASE_URL")
        return create_engine(database_url, future=True)

    def _compose_prompt(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: Mapping[str, Any] | None,
    ) -> str:
        """Combine prompts and append schema instructions when requested."""

        pieces = ["System prompt:", system_prompt.strip(), "", "User prompt:", user_prompt.strip()]
        if response_schema:
            pieces.extend([
                "",
                "Return only valid JSON that matches this schema:",
                json.dumps(dict(response_schema), indent=2, sort_keys=True),
            ])
        return "\n".join(pieces).strip()

    def _extract_text(self, response: Any) -> str:
        """Extract the text body from a Claude response object."""

        content = getattr(response, "content", None)
        if isinstance(content, list):
            pieces: list[str] = []
            for block in content:
                text_block = getattr(block, "text", None)
                if isinstance(text_block, str):
                    pieces.append(text_block)
            if pieces:
                return "".join(pieces).strip()

        text_value = getattr(response, "text", None)
        if isinstance(text_value, str):
            return text_value.strip()

        return str(response)

    def _estimate_cost(self, response: Any) -> float:
        """Estimate Claude spend using the configured per-token pricing."""

        input_tokens = float(self._extract_token_count(response, "input_tokens"))
        output_tokens = float(self._extract_token_count(response, "output_tokens"))
        return (input_tokens * 0.000003) + (output_tokens * 0.000015)

    def _extract_token_count(self, response: Any, attribute_name: str) -> int:
        """Extract a token count from Claude response usage metadata."""

        usage = getattr(response, "usage", None)
        value = getattr(usage, attribute_name, 0) if usage is not None else 0
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _daily_spend_query(self, engine):
        """Build the spend query, preferring the PostgreSQL view when present."""

        inspector = inspect(engine)
        if "daily_claude_spend" in inspector.get_view_names():
            return text(
                "SELECT COALESCE(total_spend, 0) AS total_spend "
                "FROM daily_claude_spend WHERE day = CURRENT_DATE"
            )

        dialect_name = engine.dialect.name.lower()
        if dialect_name == "sqlite":
            return text(
                "SELECT COALESCE(SUM(CAST(cost_usd AS FLOAT)), 0) AS total_spend "
                "FROM llm_calls WHERE provider LIKE 'anthropic%' AND date(created_at) = date('now')"
            )

        return text(
            "SELECT COALESCE(SUM(CAST(cost_usd AS FLOAT)), 0) AS total_spend "
            "FROM llm_calls WHERE provider ILIKE 'anthropic%' AND DATE(created_at) = CURRENT_DATE"
        )

    def _record_call(
        self,
        *,
        agent_name: str,
        provider: str,
        model: str,
        prompt: str,
        response: dict[str, Any] | str,
        confidence: float | None,
        cost_usd: float,
        input_tokens: int,
        output_tokens: int,
        run_id: str | None = None,
    ) -> None:
        """Persist a Claude ledger row using whichever llm_calls columns exist."""

        engine = self._engine_for_settings()
        metadata = MetaData()
        table = Table("llm_calls", metadata, autoload_with=engine)
        existing_columns = {column.name for column in table.columns}

        payload: dict[str, Any] = {
            "run_id": run_id,
            "agent": agent_name,
            "provider": provider,
            "model": model,
            "prompt": self._serialize_for_column(table, "prompt", prompt),
            "response": self._serialize_for_column(table, "response", response),
            "confidence": confidence,
            "cost_usd": cost_usd,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }

        insert_payload = {
            key: value
            for key, value in payload.items()
            if key in existing_columns and value is not None
        }

        with engine.begin() as connection:
            connection.execute(table.insert().values(**insert_payload))

    def _serialize_for_column(self, table: Table, column_name: str, value: Any) -> Any:
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


__all__ = ["ClaudeClient", "DEFAULT_CLAUDE_MODEL"]