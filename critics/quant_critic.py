"""Quant critic: checks numeric consistency in PM1 drafts.

The critic expects the incoming message payload to contain either explicit
`stated_target_price` and `model_target_price` keys or a `report_draft_md`
string from which a target price can be extracted. If the stated target price
deviates from the model by more than 20% the critic returns a FATAL verdict.
"""

from __future__ import annotations

import re
from typing import Optional

from core.schemas import M9CritiqueVerdict
from core.bus import Message
from .base_critic import BaseCritic


class QuantCritic(BaseCritic):
    """Validate numerical and valuation consistency."""

    stream_in = "critic:quant:input"
    group_name = "critic-quant-group"
    agent_name = "quant_critic"
    critic_name = "quant"

    TARGET_RE = re.compile(r"Target:\s*\$?([0-9,]+(?:\.[0-9]+)?)", re.IGNORECASE)

    def _parse_target_from_md(self, md: str) -> Optional[float]:
        if not md:
            return None
        m = self.TARGET_RE.search(md)
        if not m:
            return None
        return float(m.group(1).replace(",", ""))

    def process(self, message: Message) -> M9CritiqueVerdict:
        # Run deterministic checks first
        payload = message.payload or {}
        stated = payload.get("stated_target_price") or self._parse_target_from_md(payload.get("report_draft_md", ""))
        model = payload.get("model_target_price") or (payload.get("model") or {}).get("target_price")

        deterministic_verdict = None
        try:
            if stated is not None and model is not None:
                stated_f = float(stated)
                model_f = float(model)
                if model_f == 0:
                    deterministic_verdict = M9CritiqueVerdict.model_construct(
                        critic=self.critic_name,
                        verdict="WARN",
                        issues=["model_target_price_zero"],
                        iteration=payload.get("iteration") or 1,
                        pipeline_run_id=message.pipeline_run_id or "",
                    )
                else:
                    diff = abs(stated_f - model_f) / model_f
                    if diff > 0.20:
                        deterministic_verdict = M9CritiqueVerdict.model_construct(
                            critic=self.critic_name,
                            verdict="FATAL",
                            issues=[f"target_price_mismatch: stated {stated_f} vs model {model_f} ({diff:.2%})"],
                            iteration=payload.get("iteration") or 1,
                            pipeline_run_id=message.pipeline_run_id or "",
                        )
        except Exception:
            # On any parse error be conservative
            deterministic_verdict = M9CritiqueVerdict.model_construct(
                critic=self.critic_name,
                verdict="WARN",
                issues=["quant_parse_error"],
                iteration=payload.get("iteration") or 1,
                pipeline_run_id=message.pipeline_run_id or "",
            )

        # If a deterministic check is FATAL, return it immediately to avoid LLM call
        if deterministic_verdict and deterministic_verdict.verdict == "FATAL":
            return deterministic_verdict

        # Attempt to get an LLM judgment via the base implementation.
        verdict = super().process(message)

        # Merge deterministic warnings if LLM verdict is not FATAL
        if deterministic_verdict and deterministic_verdict.verdict == "WARN" and verdict.verdict != "FATAL":
            issues = list(verdict.issues or [])
            for issue in deterministic_verdict.issues:
                if issue not in issues:
                    issues.append(issue)
            verdict = M9CritiqueVerdict.model_construct(
                critic=self.critic_name,
                verdict="WARN",
                issues=issues,
                iteration=verdict.iteration or payload.get("iteration") or 1,
                pipeline_run_id=verdict.pipeline_run_id or message.pipeline_run_id or "",
            )

        return verdict


__all__ = ["QuantCritic"]
