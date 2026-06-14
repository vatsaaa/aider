"""PM1 thesis agent for drafting the investment note.

This agent consumes the AV3 valuation output and critic revision messages,
loads the upstream context from PostgreSQL, asks Claude for the prose and
structured report sections, renders the draft markdown report, persists the
draft state, and fans out the same M8 payload to all three critic streams.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel

from core.agent_base import BaseAgent
from core.bus import Message
from core.exceptions import FatalError
from core.schemas import M7ValuationOutput, M8DraftReport, MessageEnvelope
from db.idempotent_writes import upsert_report


ROOT_DIR = Path(__file__).resolve().parents[1]
PROMPT_DIR = ROOT_DIR / "config" / "prompts"
REPORT_TEMPLATE_DIR = ROOT_DIR / "reporting" / "templates"
PM1_THESIS_PROMPT = "pm1_thesis.j2"
PM1_REVISION_PROMPT = "pm1_revision.j2"
REPORT_TEMPLATE = "base_report.md.j2"
CRITIC_STREAMS = ("critic:quant:input", "critic:logic:input", "critic:data:input")


class PM1ThesisAgent(BaseAgent):
    """Generate the draft research note and coordinate revision cycles."""

    stream_in = ("stage:av3:output", "critic:revision:input")
    stream_out = "critic:quant:input"
    group_name = "pm1-group"
    agent_name = "pm1_thesis"

    revision_stream = "critic:revision:input"

    def publish_result(self, result: BaseModel, original: Message) -> None:
        """Suppress the base publish step because PM1 fans out to critic streams itself."""

        return None

    def process(self, message: Message) -> M8DraftReport:
        """Process a message using the stream encoded on the message itself."""

        return self._process_message(message, message.stream)

    def _handle_message(self, message: Message, stream_type: str) -> M8DraftReport | None:
        """Process a single message, acking or routing it to the DLQ as needed."""

        started_at = time.perf_counter()
        try:
            result = self._process_message(message, stream_type)
        except FatalError as error:
            self.bus.publish_dlq(
                error.reason,
                message.stream,
                message.data,
                error.run_id or message.pipeline_run_id,
            )
            self.bus.ack(message.stream, self.group_name, message.id)
            self._log_error(message, error, started_at)
            raise
        except Exception as error:
            self._log_error(message, error, started_at)
            return None

        self.bus.ack(message.stream, self.group_name, message.id)
        self._log_success(message, result, started_at)
        return result

    def _process_message(self, message: Message, stream_type: str) -> M8DraftReport:
        """Dispatch a message to the draft or revision processing path."""

        if stream_type == self.revision_stream:
            return self._process_revision(message)
        return self._process_initial_draft(message)

    def _process_initial_draft(self, message: Message) -> M8DraftReport:
        """Load upstream context, call Claude, and create the first draft."""

        valuation = self._parse_valuation(message)
        context = self._load_context(message, valuation)
        prompt_context = self._build_thesis_prompt_context(context=context, valuation=valuation)
        llm_sections = self._call_thesis_llm(PM1_THESIS_PROMPT, prompt_context, max_tokens=4000)
        report_context = self._build_report_context(
            context=context,
            valuation=valuation,
            llm_sections=llm_sections,
            iteration=1,
            issues=[],
        )
        markdown = self._render_report_markdown(report_context)
        result = M8DraftReport(
            report_draft_md=markdown,
            iteration=1,
            model_id=valuation.model_id,
            run_id=context["run_id"],
        )
        self._persist_report(context["run_id"], valuation.model_id, context["ticker"], result)
        self._publish_to_critics(result, message)
        return result

    def _process_revision(self, message: Message) -> M8DraftReport:
        """Revise the current draft using the critic issues in the message."""

        run_id = self._extract_run_id(message)
        report_row = self._load_report_row(run_id)
        if report_row is None:
            raise FatalError("report_missing", run_id=run_id)

        current_iteration = int(report_row.get("iteration") or 1)
        next_iteration = current_iteration + 1
        if next_iteration > self.settings.MAX_REVISION_ITERATIONS:
            raise FatalError("max_revisions_exceeded", run_id=run_id)

        valuation = self._load_valuation_from_report(report_row, run_id)
        context = self._load_context(message, valuation)
        issues = self._extract_issues(message)
        prompt_context = self._build_revision_prompt_context(
            context=context,
            valuation=valuation,
            issues=issues,
            current_draft=str(report_row.get("draft_md") or report_row.get("final_md") or ""),
            iteration=current_iteration,
        )
        llm_sections = self._call_thesis_llm(PM1_REVISION_PROMPT, prompt_context, max_tokens=2000)
        report_context = self._build_report_context(
            context=context,
            valuation=valuation,
            llm_sections=llm_sections,
            iteration=next_iteration,
            issues=issues,
        )
        markdown = self._render_report_markdown(report_context)
        result = M8DraftReport(
            report_draft_md=markdown,
            iteration=next_iteration,
            model_id=valuation.model_id,
            run_id=run_id,
        )
        self._persist_report(run_id, valuation.model_id, context["ticker"], result)
        self._publish_to_critics(result, message)
        return result

    def _parse_valuation(self, message: Message) -> M7ValuationOutput:
        """Validate the incoming valuation payload as an M7 schema."""

        payload = message.payload or {}
        if isinstance(payload, dict) and payload.get("payload") and isinstance(payload["payload"], dict):
            payload = payload["payload"]
        return M7ValuationOutput.model_validate(payload)

    def _extract_run_id(self, message: Message) -> str:
        """Return the pipeline run identifier for the current message."""

        if message.pipeline_run_id:
            return str(message.pipeline_run_id)
        payload = message.payload if isinstance(message.payload, dict) else {}
        run_id = payload.get("run_id") or payload.get("pipeline_run_id")
        if run_id:
            return str(run_id)
        raise FatalError("run_id_missing")

    def _load_context(self, message: Message, valuation: M7ValuationOutput) -> dict[str, Any]:
        """Load the upstream model and data-package context for the report."""

        run_id = self._extract_run_id(message)
        financial_model = self._load_financial_model(valuation.model_id)
        data_package = self._load_data_package(run_id)
        return {
            "run_id": run_id,
            "ticker": message.ticker or financial_model.get("ticker") or data_package.get("ticker") or "",
            "financial_model": financial_model,
            "data_package": data_package,
            "valuation_payload": valuation.model_dump(),
        }

    def _load_financial_model(self, model_id: str) -> dict[str, Any]:
        """Load the financial model payload for the given model identifier."""

        row = self.repository.load_financial_model_by_id(model_id)
        if row is None:
            raise FatalError("financial_model_missing", run_id=model_id)
        return self._jsonify_row(row)

    def _load_data_package(self, run_id: str) -> dict[str, Any]:
        """Load the most recent data package for a pipeline run."""

        row = self.repository.load_latest_data_package_by_run_id(run_id)
        if row is None:
            raise FatalError("data_package_missing", run_id=run_id)
        return self._jsonify_row(row)

    def _load_report_row(self, run_id: str) -> dict[str, Any] | None:
        """Load the most recent report row for a run, if one exists."""

        row = self.repository.load_report_by_run_id(run_id)
        if row is None:
            return None
        return self._jsonify_row(row)

    def _load_valuation_from_report(self, report_row: dict[str, Any], run_id: str) -> M7ValuationOutput:
        """Recover the valuation payload from an existing report row."""

        if report_row.get("model_id") is None:
            raise FatalError("report_model_missing", run_id=run_id)

        row = self.repository.load_financial_model_by_id(str(report_row["model_id"]))
        if row is None:
            raise FatalError("financial_model_missing", run_id=run_id)

        payload = self._jsonify_row(row).get("payload") or {}
        valuation_payload = self._extract_nested_valuation(payload)
        if not valuation_payload:
            valuation_payload = {
                "model_id": str(report_row["model_id"]),
                "rating": str(report_row.get("rating") or "HOLD"),
                "target_price": float(report_row.get("target_price") or 0.0),
                "dcf_value": float(report_row.get("target_price") or 0.0),
                "peer_multiple_value": float(report_row.get("target_price") or 0.0),
                "reasoning": str(report_row.get("draft_md") or ""),
            }
        return M7ValuationOutput.model_validate(valuation_payload)

    def _extract_nested_valuation(self, payload: Any) -> dict[str, Any]:
        """Return the valuation dictionary nested inside a financial-model payload."""

        if not isinstance(payload, dict):
            return {}
        if isinstance(payload.get("valuation"), dict):
            return dict(payload["valuation"])
        if isinstance(payload.get("m7"), dict):
            return dict(payload["m7"])
        if {"rating", "target_price", "dcf_value", "peer_multiple_value", "model_id", "reasoning"}.issubset(payload.keys()):
            return dict(payload)
        return {}

    def _call_thesis_llm(self, template_name: str, context: dict[str, Any], *, max_tokens: int) -> dict[str, Any]:
        """Render the PM1 prompt template and call the configured LLM."""

        system_prompt = self._render_prompt(template_name, context)
        user_prompt = self._render_prompt(template_name, context)
        response = self.call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_schema=None,
            max_tokens=max_tokens,
        )
        return self._normalize_llm_response(response, context)

    def _render_prompt(self, template_name: str, context: dict[str, Any]) -> str:
        """Render a prompt template from `config/prompts`."""

        environment = Environment(loader=FileSystemLoader(str(PROMPT_DIR)), autoescape=False)
        template = environment.get_template(template_name)
        return template.render(**context)

    def _normalize_llm_response(self, response: str | dict[str, Any] | BaseModel | None, context: dict[str, Any]) -> dict[str, Any]:
        """Normalise the LLM response into the report-section dictionary shape."""

        if isinstance(response, BaseModel):
            response = response.model_dump()
        elif isinstance(response, str):
            try:
                response = json.loads(response)
            except json.JSONDecodeError:
                response = {"investment_thesis": response}
        if not isinstance(response, dict):
            response = {}

        sections = response.get("sections") if isinstance(response.get("sections"), dict) else response
        if not isinstance(sections, dict):
            sections = {}

        return {
            "investment_thesis": self._coerce_text(sections.get("investment_thesis") or sections.get("thesis"), self._default_investment_thesis(context)),
            "business_model": self._coerce_text(sections.get("business_model"), self._default_business_model(context)),
            "earnings_review": self._coerce_text(sections.get("earnings_review"), self._default_earnings_review(context)),
            "risk_factors": self._coerce_text(sections.get("risk_factors"), self._default_risk_factors(context)),
            "dcf_detail": self._coerce_text(sections.get("dcf_detail"), self._default_dcf_detail(context)),
            "peer_comp_table": self._coerce_text(sections.get("peer_comp_table"), self._default_peer_comp_table(context)),
            "scenarios": self._normalize_scenarios(sections.get("scenarios"), context),
            "sensitivity_table": self._normalize_sensitivity_table(sections.get("sensitivity_table"), context),
            "sensitivity_growth_rates": self._normalize_growth_rates(sections.get("sensitivity_growth_rates")),
            "financial_summary_rows": self._normalize_summary_rows(sections.get("financial_summary_rows"), context),
        }

    def _coerce_text(self, value: Any, fallback: str) -> str:
        """Coerce a prompt field to a non-empty string, using a fallback when needed."""

        if isinstance(value, str) and value.strip():
            return value.strip()
        return fallback

    def _normalize_scenarios(self, value: Any, context: dict[str, Any]) -> dict[str, str]:
        """Return the three scenario narratives required by the report template."""

        if isinstance(value, dict):
            bear = self._coerce_text(value.get("bear"), self._default_scenario_text(context, "bear"))
            base = self._coerce_text(value.get("base"), self._default_scenario_text(context, "base"))
            bull = self._coerce_text(value.get("bull"), self._default_scenario_text(context, "bull"))
            return {"bear": bear, "base": base, "bull": bull}
        return {
            "bear": self._default_scenario_text(context, "bear"),
            "base": self._default_scenario_text(context, "base"),
            "bull": self._default_scenario_text(context, "bull"),
        }

    def _normalize_sensitivity_table(self, value: Any, context: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Return the four-by-four WACC / growth sensitivity table."""

        growth_rates = self._normalize_growth_rates(None)
        wacc_labels = ["9.0%", "10.0%", "11.0%", "12.0%"]
        if isinstance(value, dict):
            table: dict[str, dict[str, Any]] = {}
            for wacc_label in wacc_labels:
                row = value.get(wacc_label)
                if isinstance(row, dict):
                    table[wacc_label] = {
                        growth: row.get(growth, self._default_sensitivity_value(context, wacc_label, growth))
                        for growth in growth_rates
                    }
                else:
                    table[wacc_label] = {growth: self._default_sensitivity_value(context, wacc_label, growth) for growth in growth_rates}
            return table

        return {
            wacc_label: {growth: self._default_sensitivity_value(context, wacc_label, growth) for growth in growth_rates}
            for wacc_label in wacc_labels
        }

    def _normalize_growth_rates(self, value: Any) -> list[str]:
        """Return the terminal growth labels used by the markdown template."""

        if isinstance(value, list) and value:
            growth_rates = [str(item) for item in value if str(item).strip()]
            if growth_rates:
                return growth_rates
        return ["2.0%", "2.5%", "3.0%", "3.5%"]

    def _normalize_summary_rows(self, value: Any, context: dict[str, Any]) -> list[dict[str, Any]]:
        """Return the financial summary rows displayed near the front of the report."""

        if isinstance(value, list) and value:
            rows: list[dict[str, Any]] = []
            for row in value:
                if isinstance(row, dict) and row.get("metric"):
                    rows.append(
                        {
                            "metric": str(row.get("metric")),
                            "fy_minus_1": row.get("fy_minus_1", ""),
                            "fy_0": row.get("fy_0", ""),
                            "fy_1": row.get("fy_1", ""),
                            "fy_2": row.get("fy_2", ""),
                        }
                    )
            if rows:
                return rows

        ticker = context["ticker"]
        valuation = context["valuation_payload"]
        return [
            {
                "metric": "Target Price",
                "fy_minus_1": "-",
                "fy_0": f"${valuation['target_price']:.2f}",
                "fy_1": f"${valuation['target_price']:.2f}",
                "fy_2": f"${valuation['target_price']:.2f}",
            },
            {
                "metric": f"{ticker} Valuation",
                "fy_minus_1": "-",
                "fy_0": f"{valuation['rating']}",
                "fy_1": f"DCF {valuation['dcf_value']:.2f}",
                "fy_2": f"Peer {valuation['peer_multiple_value']:.2f}",
            },
        ]

    def _build_thesis_prompt_context(self, context: dict[str, Any], valuation: M7ValuationOutput) -> dict[str, Any]:
        """Build the context used to prompt Claude for the initial draft."""

        return {
            "ticker": context["ticker"],
            "rating": valuation.rating,
            "target_price": valuation.target_price,
            "model_id": valuation.model_id,
            "run_id": context["run_id"],
            "financial_model": context["financial_model"],
            "data_package": context["data_package"],
            "valuation_payload": valuation.model_dump(),
            "valuation": valuation.model_dump(),
        }

    def _build_revision_prompt_context(
        self,
        *,
        context: dict[str, Any],
        valuation: M7ValuationOutput,
        issues: list[str],
        current_draft: str,
        iteration: int,
    ) -> dict[str, Any]:
        """Build the context used to prompt Claude for a targeted revision."""

        return {
            "ticker": context["ticker"],
            "rating": valuation.rating,
            "target_price": valuation.target_price,
            "model_id": valuation.model_id,
            "run_id": context["run_id"],
            "issues": issues,
            "current_draft": current_draft,
            "iteration": iteration,
            "financial_model": context["financial_model"],
            "data_package": context["data_package"],
            "valuation_payload": valuation.model_dump(),
            "valuation": valuation.model_dump(),
        }

    def _build_report_context(
        self,
        *,
        context: dict[str, Any],
        valuation: M7ValuationOutput,
        llm_sections: dict[str, Any],
        iteration: int,
        issues: list[str],
    ) -> dict[str, Any]:
        """Combine the LLM output with deterministic defaults for the markdown report."""

        return {
            "ticker": context["ticker"],
            "rating": valuation.rating,
            "target_price": valuation.target_price,
            "date": datetime.now(timezone.utc).date().isoformat(),
            "investment_thesis": llm_sections["investment_thesis"],
            "financial_summary_rows": llm_sections["financial_summary_rows"],
            "business_model": llm_sections["business_model"],
            "earnings_review": llm_sections["earnings_review"],
            "scenarios": llm_sections["scenarios"],
            "sensitivity_table": llm_sections["sensitivity_table"],
            "sensitivity_growth_rates": llm_sections["sensitivity_growth_rates"],
            "risk_factors": llm_sections["risk_factors"],
            "dcf_detail": llm_sections["dcf_detail"],
            "peer_comp_table": llm_sections["peer_comp_table"],
            "run_id": context["run_id"],
            "model_id": valuation.model_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "issues": issues,
            "iteration": iteration,
        }

    def _render_report_markdown(self, context: dict[str, Any]) -> str:
        """Render the PM1 markdown report using the shared report template."""

        environment = Environment(loader=FileSystemLoader(str(REPORT_TEMPLATE_DIR)), autoescape=False)
        template = environment.get_template(REPORT_TEMPLATE)
        return template.render(**context)

    def _default_investment_thesis(self, context: dict[str, Any]) -> str:
        """Generate a deterministic fallback investment thesis."""

        valuation = context["valuation_payload"]
        return (
            f"{context['ticker']} is rated {valuation['rating']} because the valuation work points to a target price of "
            f"${valuation['target_price']:.2f} and the catalyst set supports a multi-quarter re-rating."
        )

    def _default_business_model(self, context: dict[str, Any]) -> str:
        """Generate a deterministic fallback business-model paragraph."""

        return (
            f"{context['ticker']} combines a durable core franchise with recurring revenue and a balance sheet that can support execution."
        )

    def _default_earnings_review(self, context: dict[str, Any]) -> str:
        """Generate a deterministic fallback earnings review paragraph."""

        return (
            f"Recent results for {context['ticker']} show whether the market is underestimating margin resilience, cash conversion, and forward guidance."
        )

    def _default_risk_factors(self, context: dict[str, Any]) -> str:
        """Generate a deterministic fallback risk-factor paragraph."""

        valuation = context["valuation_payload"]
        return (
            f"Key risks include execution slippage, multiple compression, and any deterioration that would move the {valuation['rating']} thesis away from the current ${valuation['target_price']:.2f} target."
        )

    def _default_dcf_detail(self, context: dict[str, Any]) -> str:
        """Generate a deterministic fallback DCF detail paragraph."""

        valuation = context["valuation_payload"]
        return (
            f"DCF detail centers on a modeled value of ${valuation['dcf_value']:.2f} per share and a peer cross-check at ${valuation['peer_multiple_value']:.2f}."
        )

    def _default_peer_comp_table(self, context: dict[str, Any]) -> str:
        """Generate a deterministic fallback peer-comparison paragraph."""

        return (
            f"The peer comparison emphasizes sector-relative valuation rather than a standalone absolute multiple for {context['ticker']}."
        )

    def _default_scenario_text(self, context: dict[str, Any], scenario_name: str) -> str:
        """Generate deterministic scenario prose for the report template."""

        valuation = context["valuation_payload"]
        description = {
            "bear": "slower growth, compressed margins, and a valuation reset",
            "base": "steady execution and a valuation that tracks the modeled base case",
            "bull": "faster growth, better margins, and a premium rerating",
        }[scenario_name]
        return (
            f"{scenario_name.title()} case: {description} keep the thesis anchored to a {valuation['rating']} stance and a ${valuation['target_price']:.2f} target."
        )

    def _default_sensitivity_value(self, context: dict[str, Any], wacc_label: str, growth_label: str) -> float:
        """Compute a deterministic placeholder sensitivity cell value."""

        target_price = float(context["valuation_payload"]["target_price"])
        wacc_index = {"9.0%": 0, "10.0%": 1, "11.0%": 2, "12.0%": 3}[wacc_label]
        growth_index = {"2.0%": 0, "2.5%": 1, "3.0%": 2, "3.5%": 3}[growth_label]
        value = target_price * (1.0 - (0.03 * wacc_index)) * (1.0 + (0.02 * growth_index))
        return round(value, 2)

    def _persist_report(self, run_id: str, model_id: str, ticker: str, draft: M8DraftReport) -> None:
        """Persist the current draft state to the reports table."""

        upsert_report(
            self.db,
            run_id=run_id,
            model_id=model_id,
            ticker=ticker,
            iteration=draft.iteration,
            status="draft",
            draft_md=draft.report_draft_md,
            final_md=None,
            rating=self._extract_rating_from_markdown_or_default(draft.report_draft_md),
            target_price=self._extract_target_price_from_markdown_or_default(draft.report_draft_md),
            report_id=None,
            created_at=datetime.now(timezone.utc),
        )

    def _extract_rating_from_markdown_or_default(self, markdown: str) -> str:
        """Return the rating stored in the markdown or a safe default."""

        for rating in ("BUY", "HOLD", "SELL"):
            if rating in markdown:
                return rating
        return "HOLD"

    def _extract_target_price_from_markdown_or_default(self, markdown: str) -> float:
        """Return a target price from the markdown if one can be located."""

        marker = "Target: $"
        if marker not in markdown:
            return 0.0
        fragment = markdown.split(marker, 1)[1]
        digits = []
        for char in fragment:
            if char.isdigit() or char in ".,":
                digits.append(char)
            else:
                break
        try:
            return float("".join(digits).replace(",", ""))
        except ValueError:
            return 0.0

    def _publish_to_critics(self, draft: M8DraftReport, original: Message) -> None:
        """Fan out the same M8 payload to the three critic input streams."""

        envelope = MessageEnvelope(
            message_id=str(uuid4()),
            pipeline_run_id=draft.run_id,
            trigger_type=original.trigger_type or original.data.get("trigger_type", "manual"),
            ticker=original.ticker or original.data.get("ticker", ""),
            timestamp=datetime.now(timezone.utc).isoformat(),
            payload=draft.model_dump(),
            metadata={**dict(original.metadata or {}), "llm_used": "anthropic/claude-sonnet-4-20250514", "iteration": draft.iteration},
        )
        payload = envelope.model_dump()
        for stream in CRITIC_STREAMS:
            self.bus.publish(stream, payload)

    def _extract_issues(self, message: Message) -> list[str]:
        """Extract critic issues from a revision message payload."""

        payload = message.payload if isinstance(message.payload, dict) else {}
        if not payload and isinstance(message.data, dict):
            nested_payload = message.data.get("payload")
            if isinstance(nested_payload, dict):
                payload = nested_payload

        issues = payload.get("issues")
        if isinstance(issues, list):
            return [str(issue) for issue in issues if str(issue).strip()]

        nested = payload.get("verdict") if isinstance(payload.get("verdict"), dict) else None
        if isinstance(nested, dict) and isinstance(nested.get("issues"), list):
            return [str(issue) for issue in nested["issues"] if str(issue).strip()]
        return []

    def _jsonify_row(self, row: dict[str, Any]) -> dict[str, Any]:
        """Convert any JSON-backed columns in a DB row into Python objects."""

        converted = dict(row)
        for key, value in list(converted.items()):
            if isinstance(value, str):
                try:
                    converted[key] = json.loads(value)
                except json.JSONDecodeError:
                    continue
        return converted

    def _log_success(self, message: Message, result: BaseModel, started_at: float) -> None:
        """Emit a structured success log line for a processed message."""

        self.log(
            "agent_success",
            level="info",
            run_id=message.pipeline_run_id,
            ticker=message.ticker,
            stream=message.stream,
            duration_ms=int((time.perf_counter() - started_at) * 1000),
            result_type=result.__class__.__name__,
        )

    def _log_error(self, message: Message, error: Exception, started_at: float) -> None:
        """Emit a structured error log line for a failed message."""

        self.log(
            "agent_error",
            level="error",
            run_id=message.pipeline_run_id,
            ticker=message.ticker,
            stream=message.stream,
            duration_ms=int((time.perf_counter() - started_at) * 1000),
            error_type=error.__class__.__name__,
            error_message=str(error),
        )


__all__ = ["PM1ThesisAgent"]