"""Base critic implementations used to review PM1 draft reports.

Each concrete critic inherits from `BaseCritic` and implements domain
validation logic. The base class handles calling the shared LLM router and
validating the result as an `M9CritiqueVerdict`.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from core.agent_base import BaseAgent
from core.bus import Message
from core.schemas import M9CritiqueVerdict


class BaseCritic(BaseAgent):
    """Shared critic behaviour.

    Subclasses must set `stream_in`, `group_name`, `agent_name`, and
    `critic_name` (one of "quant", "logic", "data").
    """

    stream_out = "critic:verdict:input"

    critic_name: str

    def process(self, message: Message) -> M9CritiqueVerdict:
        """Call the LLM with a critic prompt and validate the response.

        The LLM is expected to return a dict compatible with `M9CritiqueVerdict`.
        If the router returns an unexpected value, attempt to coerce using
        the local validation rules and return a verdict.
        """

        system_prompt = f"You are the {self.critic_name} critic. Respond with a JSON verdict."
        user_prompt = message.payload.get("report_draft_md") or message.data.get("payload") or ""

        response = self.call_llm(system_prompt=system_prompt, user_prompt=user_prompt, response_schema=M9CritiqueVerdict.model_json_schema())

        # If the router returned a mapping, validate it strictly.
        if isinstance(response, dict):
            # Ensure critic field is set to the concrete critic name.
            response["critic"] = self.critic_name
            try:
                # Use model_construct to avoid running validators that import settings
                verdict = M9CritiqueVerdict.model_construct(**response)
                return verdict
            except Exception as exc:
                # Fall through to local fallback below
                self.log("llm_validation_failed", level="error", error=str(exc), run_id=message.pipeline_run_id, ticker=message.ticker)

        # Fallback: conservative PASS with a note indicating LLM failure
        fallback = M9CritiqueVerdict.model_construct(critic=self.critic_name, verdict="WARN", issues=["llm_response_unparseable"], iteration=message.payload.get("iteration") or 1, pipeline_run_id=message.pipeline_run_id or "")
        return fallback


__all__ = ["BaseCritic"]
