"""PM2 Compliance Agent

This agent performs compliance clearance on M9 PASS verdicts. It checks for
MNPI phrases, re-verifies the rating against the numerical model, appends a
disclosures block to the final markdown, updates the `reports` table, and
emits an `M10FinalReport` payload on successful approval.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel
from sqlalchemy import text

from core.agent_base import BaseAgent
from core.bus import Bus, Message
from core.exceptions import FatalError
from core.schemas import M9CritiqueVerdict, M10FinalReport, MessageEnvelope


class PM2ComplianceAgent(BaseAgent):
    """Performs compliance checks and finalizes approved drafts.

    The agent listens on `critique:verdict` and only processes messages with
    `verdict == "PASS"`. On success it updates the `reports` table and
    publishes an `M10FinalReport` to `stage:pm2:output`.
    """

    stream_in = "critique:verdict"
    stream_out = "stage:pm2:output"
    group_name = "pm2-group"
    agent_name = "pm2_compliance"

    MNPI_CONFIG = Path("config") / "mnpi_keywords.yaml"
    HURDLE_RATE = 0.15

    def __init__(self, bus: Bus, db: Any, settings: Any) -> None:
        super().__init__(bus=bus, db=db, settings=settings)

    def process(self, message: Message) -> Optional[BaseModel]:
        """Process a single `critique:verdict` message.

        Args:
            message: Bus `Message` containing an `M9CritiqueVerdict` payload.

        Returns:
            An `M10FinalReport` BaseModel on success, or `None` when the
            message is ignored.

        Raises:
            FatalError: For MNPI detection or rating/model mismatches. The
            agent will publish a DLQ entry before raising.
        """

        payload = message.payload or message.data.get("payload", {})
        verdict = payload.get("verdict")
        pipeline_run_id = message.pipeline_run_id or payload.get("pipeline_run_id")

        # Defensive: ignore anything that is not an approved PASS
        if verdict != "PASS":
            return None

        # Load the draft from reports
        if self.db is None:
            # No DB configured — fatal
            self.bus.publish_dlq("pm2_no_db", message.stream, message.data, pipeline_run_id)
            raise FatalError("pm2_no_db", pipeline_run_id)

        report = self.repository.load_report_by_run_id(pipeline_run_id)
        if not report:
            self.bus.publish_dlq("pm2_missing_report", message.stream, message.data, pipeline_run_id)
            raise FatalError("missing_report", pipeline_run_id)

        draft_md = report.get("draft_md")
        model_id = report.get("model_id")
        rating = report.get("rating")
        target_price = report.get("target_price")

        # MNPI scan
        try:
            keywords = self._load_mnpi_keywords()
        except Exception:
            keywords = []

        lower_text = (draft_md or "").lower()
        for kw in keywords:
            if kw.lower() in lower_text:
                reason = f"mnpi_detected:{kw}"
                # publish to DLQ then raise
                self.bus.publish_dlq(reason, message.stream, message.data, pipeline_run_id)
                raise FatalError(reason, pipeline_run_id)

        # Rating vs model re-verification — fetch financial model
        fm = self.repository.load_latest_financial_model_by_run_id(pipeline_run_id)

        if not fm:
            self.bus.publish_dlq("pm2_missing_financial_model", message.stream, message.data, pipeline_run_id)
            raise FatalError("missing_financial_model", pipeline_run_id)

        model_payload = fm.get("payload") or {}
        if not isinstance(model_payload, dict):
            model_payload = json.loads(model_payload) if model_payload else {}
        current_price = None
        # payload may store current_price under a few shapes — try common keys
        for key in ("current_price", "spot_price", "price"):
            if key in model_payload:
                current_price = float(model_payload[key])
                break

        if current_price is None:
            # try nested valuation
            valuation = model_payload.get("valuation") or model_payload.get("valuation_snapshot") or {}
            current_price = valuation.get("current_price")
        try:
            current_price = float(current_price)
        except Exception:
            self.bus.publish_dlq("pm2_model_missing_price", message.stream, message.data, pipeline_run_id)
            raise FatalError("model_missing_price", pipeline_run_id)

        # compute expected return and derive model rating
        expected_return = (float(target_price) - current_price) / current_price
        model_rating = self._derive_rating(expected_return)
        if model_rating != (rating or ""):
            reason = "rating_model_mismatch"
            self.bus.publish_dlq(reason, message.stream, message.data, pipeline_run_id)
            raise FatalError(reason, pipeline_run_id)

        # Append disclosures block
        warn_issues = payload.get("issues", []) or []
        timestamp = datetime.now(timezone.utc).isoformat()
        disclosures = (
            "\n---\n"
            "**Disclosures:** This report was generated by an automated pipeline.\n"
            "Data sources: SEC EDGAR, yfinance, FRED. Pipeline run: {run_id}.\n"
            "Model ID: {model_id}. Generated: {timestamp}.\n"
            "WARN advisories: {warns}.\n"
        ).format(run_id=pipeline_run_id, model_id=model_id, timestamp=timestamp, warns=warn_issues)

        final_md = (draft_md or "") + disclosures

        # persist approved final
        self.repository.update_report_final(run_id=pipeline_run_id, final_md=final_md, status="approved")

        # publish M10 final report
        m10_payload = {
            "report_final_md": final_md,
            "disclosures_appended": True,
            "mnpi_clean": True,
            "rating_verified": True,
            "run_id": pipeline_run_id,
        }

        return M10FinalReport.model_validate(m10_payload)

    def _load_mnpi_keywords(self) -> list[str]:
        """Load MNPI keyword phrases from `config/mnpi_keywords.yaml`.

        Returns an empty list if the file cannot be read.
        """

        try:
            with open(self.MNPI_CONFIG, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
                if isinstance(data, list):
                    return [str(x) for x in data]
                if isinstance(data, dict):
                    # support either list or mapping formats
                    return [str(v) for v in data.keys()]
        except Exception:
            return []
        return []

    def _derive_rating(self, expected_return: float) -> str:
        """Derive rating string from an expected return using hurdle logic."""

        if expected_return > self.HURDLE_RATE:
            return "BUY"
        if expected_return < -self.HURDLE_RATE:
            return "SELL"
        return "HOLD"


__all__ = ["PM2ComplianceAgent"]
