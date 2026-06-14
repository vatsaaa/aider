"""Logic critic: checks narrative consistency and risk quantification."""

from __future__ import annotations

import re

from core.schemas import M9CritiqueVerdict
from core.bus import Message
from .base_critic import BaseCritic


class LogicCritic(BaseCritic):
    """Validate Page 1 specificity, hedging, contradictions and quantified risks."""

    stream_in = "critic:logic:input"
    group_name = "critic-logic-group"
    agent_name = "logic_critic"
    critic_name = "logic"

    RISK_SECTION_RE = re.compile(r"##\s*Risk Factors(.*?)(?:##|$)", re.DOTALL | re.IGNORECASE)
    NUMBER_RE = re.compile(r"\d+(?:\.\d+)?\s*(bps|basis points|%|\$)", re.IGNORECASE)

    def _extract_risk_section(self, md: str) -> str:
        m = self.RISK_SECTION_RE.search(md or "")
        return m.group(1).strip() if m else ""

    def process(self, message: Message) -> M9CritiqueVerdict:
        payload = message.payload or {}
        md = payload.get("report_draft_md", "")

        # Page 1 specificity: must mention a catalyst with a timeframe (look for 'by' + year or 'in Q')
        page1_specific = False
        if re.search(r"\b(by\s+\d{4}|in\s+Q[1-4]|within\s+\d+\s+(days|months|years))\b", md, re.IGNORECASE):
            page1_specific = True

        # Risk factors must contain a quantified item
        risk_text = self._extract_risk_section(md)
        risk_not_quantified = False
        if risk_text and not self.NUMBER_RE.search(risk_text):
            risk_not_quantified = True

        # Hedging language detection
        hedging_detected = False
        if re.search(r"\b(may|might|could|potentially)\b\s+be\b", md, re.IGNORECASE):
            hedging_detected = True

        # Determine if we have a fatal deterministic failure
        fatal_issues = []
        if not page1_specific:
            fatal_issues.append("page1_missing_specific_catalyst_timeframe")
        if risk_not_quantified:
            fatal_issues.append("risk_factors_not_quantified")

        if fatal_issues:
            return M9CritiqueVerdict.model_construct(
                critic=self.critic_name,
                verdict="FATAL",
                issues=fatal_issues,
                iteration=payload.get("iteration") or 1,
                pipeline_run_id=message.pipeline_run_id or "",
            )

        # Attempt to get an LLM judgment via the base implementation.
        verdict = super().process(message)

        # Merge hedging language warnings if LLM did not reject the draft
        if hedging_detected and verdict.verdict != "FATAL":
            issues = list(verdict.issues or [])
            if "hedging_language_detected" not in issues:
                issues.append("hedging_language_detected")
            verdict = M9CritiqueVerdict.model_construct(
                critic=self.critic_name,
                verdict="WARN",
                issues=issues,
                iteration=verdict.iteration or payload.get("iteration") or 1,
                pipeline_run_id=verdict.pipeline_run_id or message.pipeline_run_id or "",
            )

        return verdict


__all__ = ["LogicCritic"]
