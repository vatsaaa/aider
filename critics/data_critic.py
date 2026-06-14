"""Data critic: checks reported figures against the model and MNPI phrases."""

from __future__ import annotations

import os
import re
from typing import Dict

import yaml

from core.schemas import M9CritiqueVerdict
from core.bus import Message
from .base_critic import BaseCritic


class DataCritic(BaseCritic):
    """Validate numeric fidelity, auditor flag disclosure and MNPI phrases."""

    stream_in = "critic:data:input"
    group_name = "critic-data-group"
    agent_name = "data_critic"
    critic_name = "data"

    def _load_mnpi(self) -> list[str]:
        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "mnpi_keywords.yaml")
        if not os.path.exists(path):
            # also check top-level config
            path = os.path.join("config", "mnpi_keywords.yaml")
        try:
            with open(path, "r", encoding="utf8") as fh:
                data = yaml.safe_load(fh)
                keywords = []
                def extract(item):
                    if isinstance(item, str):
                        keywords.append(item.lower())
                    elif isinstance(item, list):
                        for sub in item:
                            extract(sub)
                    elif isinstance(item, dict):
                        for k in item.keys():
                            extract(k)
                extract(data)
                return keywords
        except Exception:
            return []

    def process(self, message: Message) -> M9CritiqueVerdict:
        payload = message.payload or {}
        md = payload.get("report_draft_md", "").lower()

        fatal_issues = []
        warn_issues = []

        # MNPI detection
        mnpi_phrases = self._load_mnpi()
        for phrase in mnpi_phrases:
            if phrase in md:
                fatal_issues.append(f"mnpi_phrase_detected:{phrase}")

        # Figure checks: compare any reported figures against model values within 5%
        figures: Dict[str, float] = payload.get("figures") or {}
        model_figures: Dict[str, float] = payload.get("model_figures") or {}
        for key, reported in figures.items():
            model_value = model_figures.get(key)
            if model_value is None:
                continue
            try:
                r = float(reported)
                m = float(model_value)
                if m == 0:
                    continue
                if abs(r - m) / m > 0.05:
                    fatal_issues.append(f"figure_mismatch:{key}: reported {r} vs model {m}")
            except Exception:
                warn_issues.append(f"figure_parse_error:{key}")

        # Auditor flags must be disclosed somewhere in the draft if present in data package
        auditor_flags = payload.get("auditor_flags") or []
        for flag in auditor_flags:
            if flag.lower() not in md:
                fatal_issues.append(f"auditor_flag_not_disclosed:{flag}")

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

        # Merge warning issues if LLM did not reject the draft
        if warn_issues and verdict.verdict != "FATAL":
            issues = list(verdict.issues or [])
            for issue in warn_issues:
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


__all__ = ["DataCritic"]
