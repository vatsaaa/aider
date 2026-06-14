"""Pydantic v2 schemas for the Digital Equity Analyst message contracts.

This module defines the canonical message envelope and all stage payload
schemas used by agents across the pipeline. These models are the contract
between stages; field names must remain stable.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MessageEnvelope(BaseModel):
    """Shared outer wrapper for every bus message."""

    model_config = ConfigDict(extra="forbid")

    message_id: str
    pipeline_run_id: str
    trigger_type: Literal["8-K", "10-Q", "10-K", "earnings", "fred_release", "price_move", "thesis_expiry", "manual"]
    ticker: str
    timestamp: str
    payload: Dict[str, Any]
    metadata: Dict[str, Any]


class M1TriggerEvent(BaseModel):
    """Trigger event used by the scanner and watchers."""

    model_config = ConfigDict(extra="forbid")

    ticker: str
    trigger_type: Literal["8-K", "10-Q", "10-K", "earnings", "fred_release", "price_move", "manual"]
    pipeline_run_id: str


class M2MacroOutput(BaseModel):
    """Macro regime classification output."""

    model_config = ConfigDict(extra="forbid")

    regime: Literal["hiking", "easing", "recovery", "peak"]
    sector_overweights: List[str]
    sector_underweights: List[str]
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str


class M3SectorOutput(BaseModel):
    """Sector scoring output from RS2."""

    model_config = ConfigDict(extra="forbid")

    sector_scores: Dict[str, float]
    primary_sector: str
    reasoning: str


class CandidateTicker(BaseModel):
    """Single screening candidate with its rationale."""

    model_config = ConfigDict(extra="forbid")

    ticker: str
    rationale: str
    valuation_snapshot: Dict[str, Any] = Field(default_factory=dict)


class M4ScreenOutput(BaseModel):
    """Screening output containing ranked candidates."""

    model_config = ConfigDict(extra="forbid")

    candidates: List[CandidateTicker] = Field(min_length=1, max_length=5)


class M5DataOutput(BaseModel):
    """Data package output from the AV1 agent."""

    model_config = ConfigDict(extra="forbid")

    ticker: str
    data_package_id: str
    auditor_flags: List[str] = Field(default_factory=list)


class BearCase(BaseModel):
    """Bear scenario assumptions and output series."""

    model_config = ConfigDict(extra="forbid")

    fcf: List[float]
    ebitda_margin: List[float]
    capex: List[float]
    exit_multiple: float


class BaseCase(BaseModel):
    """Base scenario assumptions and output series."""

    model_config = ConfigDict(extra="forbid")

    fcf: List[float]
    ebitda_margin: List[float]
    capex: List[float]
    exit_multiple: float


class BullCase(BaseModel):
    """Bull scenario assumptions and output series."""

    model_config = ConfigDict(extra="forbid")

    fcf: List[float]
    ebitda_margin: List[float]
    capex: List[float]
    exit_multiple: float


class ScenarioSet(BaseModel):
    """Scenario container used inside the model output."""

    model_config = ConfigDict(extra="forbid")

    bear: BearCase
    base: BaseCase
    bull: BullCase


class M6ModelOutput(BaseModel):
    """Three-statement model output from AV2."""

    model_config = ConfigDict(extra="forbid")

    model_id: str
    wacc: float
    scenarios: ScenarioSet
    balance_ok: bool

    @model_validator(mode="after")
    def _validate_balance(self) -> "M6ModelOutput":
        """Reject unbalanced models before they can be published."""

        if self.balance_ok is False:
            raise ValueError("balance_ok must be True")
        return self


class M7ValuationOutput(BaseModel):
    """Valuation output from AV3."""

    model_config = ConfigDict(extra="forbid")

    rating: Literal["BUY", "HOLD", "SELL"]
    target_price: float
    dcf_value: float
    peer_multiple_value: float
    model_id: str
    reasoning: str


class M8DraftReport(BaseModel):
    """Draft report payload produced by PM1."""

    model_config = ConfigDict(extra="forbid")

    report_draft_md: str
    iteration: int = Field(ge=1)
    model_id: str
    run_id: str


class M9CritiqueVerdict(BaseModel):
    """Critic verdict payload used by the arbiter and PM2."""

    model_config = ConfigDict(extra="forbid")

    critic: Literal["quant", "logic", "data", "arbiter"]
    verdict: Literal["PASS", "WARN", "FATAL"]
    issues: List[str] = Field(default_factory=list)
    iteration: int
    pipeline_run_id: str

    @model_validator(mode="after")
    def _validate_iteration(self) -> "M9CritiqueVerdict":
        """Ensure the critique iteration respects pipeline bounds."""

        from core.config import settings

        if self.iteration < 1:
            raise ValueError("iteration must be >= 1")
        if self.iteration > settings.MAX_REVISION_ITERATIONS:
            raise ValueError(
                f"iteration must be <= MAX_REVISION_ITERATIONS ({settings.MAX_REVISION_ITERATIONS})"
            )
        return self


class M10FinalReport(BaseModel):
    """Final report payload after compliance review."""

    model_config = ConfigDict(extra="forbid")

    report_final_md: str
    disclosures_appended: bool
    mnpi_clean: bool
    rating_verified: bool
    run_id: str


class M11PublishReceipt(BaseModel):
    """Receipt emitted by PM3 after publishing the report."""

    model_config = ConfigDict(extra="forbid")

    git_commit_hash: str
    email_sent_at: str
    pdf_path: str
    artifact_uri: str | None = None
    run_id: str


__all__ = [
    "MessageEnvelope",
    "M1TriggerEvent",
    "M2MacroOutput",
    "M3SectorOutput",
    "CandidateTicker",
    "M4ScreenOutput",
    "M5DataOutput",
    "BearCase",
    "BaseCase",
    "BullCase",
    "ScenarioSet",
    "M6ModelOutput",
    "M7ValuationOutput",
    "M8DraftReport",
    "M9CritiqueVerdict",
    "M10FinalReport",
    "M11PublishReceipt",
]
