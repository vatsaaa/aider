"""AV2 model agent that builds the quantitative three-statement model.

This agent does not call any LLM. It consumes the AV1 `M5DataOutput`, loads
the corresponding `DataPackage` row, builds a deterministic three-statement
financial model, validates the balance sheet, persists the resulting
`financial_models` row, and emits an `M6ModelOutput` downstream.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import text

from core.agent_base import BaseAgent
from core.bus import Message
from core.exceptions import FatalError
from models.financial_model import ThreeStatementModel
from core.schemas import BaseCase, BearCase, BullCase, M5DataOutput, M6ModelOutput, ScenarioSet
from db.idempotent_writes import upsert_financial_model


def _json_loads_if_needed(value: Any) -> dict[str, Any]:
    """Convert a stored payload representation into a dictionary."""

    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return loaded if isinstance(loaded, dict) else {}
    return {}


class AV2ModelAgent(BaseAgent):
    """Agent that converts AV1 data packages into M6 model outputs."""

    stream_in = "stage:av1:output"
    stream_out = "stage:av2:output"
    group_name = "av2-group"
    agent_name = "av2_model"

    def process(self, message: Message) -> M6ModelOutput:
        """Load the data package, build the model, and return the M6 payload."""

        m5 = M5DataOutput.model_validate(message.payload)
        data_package = self._load_data_package(m5.data_package_id)

        model = ThreeStatementModel(data_package)
        wacc = model.compute_wacc()

        bear = model.run_scenario("bear")
        base = model.run_scenario("base")
        bull = model.run_scenario("bull")

        if not model.check_balance():
            raise FatalError("model_balance_failure", run_id=message.pipeline_run_id)

        scenario_set = ScenarioSet(
            bear=BearCase(**bear),
            base=BaseCase(**base),
            bull=BullCase(**bull),
        )

        existing = self.repository.load_latest_financial_model_by_run_id(message.pipeline_run_id)
        model_id = existing["model_id"] if existing else str(uuid4())

        model_output = M6ModelOutput(
            model_id=model_id,
            wacc=wacc,
            scenarios=scenario_set,
            balance_ok=True,
        )

        self._persist_model(message, m5, model_output, model)
        return model_output

    def _load_data_package(self, data_package_id: str) -> dict[str, Any]:
        """Load a data package payload from the backing database."""

        data_package = self.repository.load_data_package_by_id(data_package_id)
        if data_package is None:
            raise FatalError("data_package_missing", run_id=data_package_id)

        payload = _json_loads_if_needed(data_package.get("payload"))
        if not payload:
            raise FatalError("data_package_empty", run_id=data_package_id)
        return payload

    def _persist_model(self, message: Message, m5: M5DataOutput, model_output: M6ModelOutput, model: ThreeStatementModel) -> None:
        """Persist the computed model row to `financial_models`."""

        payload = {
            "income_statement": model.build_income_statement().to_dict(orient="index"),
            "balance_sheet": model.build_balance_sheet().to_dict(orient="index"),
            "cash_flow_statement": model.build_cash_flow_statement().to_dict(orient="index"),
        }

        self.repository.save_financial_model(
            run_id=message.pipeline_run_id,
            ticker=m5.ticker,
            payload=payload,
            scenarios=model_output.scenarios.model_dump(),
            balance_ok=True,
            wacc=model_output.wacc,
            model_id=model_output.model_id,
            built_at=datetime.now(timezone.utc),
            sensitivity_table=None,
        )


__all__ = ["AV2ModelAgent"]