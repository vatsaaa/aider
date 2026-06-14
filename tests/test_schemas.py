"""Tests for the canonical Pydantic message schemas."""

from __future__ import annotations

from copy import deepcopy
import os

import pytest
from pydantic import ValidationError

from core.schemas import (
    BearCase,
    BaseCase,
    BullCase,
    CandidateTicker,
    M1TriggerEvent,
    M2MacroOutput,
    M3SectorOutput,
    M4ScreenOutput,
    M5DataOutput,
    M6ModelOutput,
    M7ValuationOutput,
    M8DraftReport,
    M9CritiqueVerdict,
    M10FinalReport,
    M11PublishReceipt,
    MessageEnvelope,
    ScenarioSet,
)


def _valid_payloads():
    """Return representative valid payloads for all schema models."""

    return {
        "envelope": {
            "message_id": "msg-1",
            "pipeline_run_id": "run-1",
            "trigger_type": "manual",
            "ticker": "AAPL",
            "timestamp": "2026-05-22T00:00:00Z",
            "payload": {"hello": "world"},
            "metadata": {"retry_count": 0},
        },
        "m1": {
            "ticker": "AAPL",
            "trigger_type": "manual",
            "pipeline_run_id": "run-1",
        },
        "m2": {
            "regime": "hiking",
            "sector_overweights": ["Energy", "Financials"],
            "sector_underweights": ["Consumer Staples", "Healthcare", "Utilities"],
            "confidence": 0.8,
            "reasoning": "Rates remain elevated and cyclicals lead.",
        },
        "m3": {
            "sector_scores": {"Technology": 0.7, "Energy": 0.2},
            "primary_sector": "Technology",
            "reasoning": "Growth backdrop remains strongest in tech.",
        },
        "m4": {
            "candidates": [
                {
                    "ticker": "AAPL",
                    "rationale": "High quality cash flows and attractive valuation.",
                    "valuation_snapshot": {"pe": 25.0},
                }
            ]
        },
        "m5": {
            "ticker": "AAPL",
            "data_package_id": "dp-1",
            "auditor_flags": ["going_concern"],
        },
        "m6": {
            "model_id": "model-1",
            "wacc": 0.1,
            "scenarios": {
                "bear": {"fcf": [1.0], "ebitda_margin": [0.1], "capex": [0.1], "exit_multiple": 10.0},
                "base": {"fcf": [1.2], "ebitda_margin": [0.12], "capex": [0.09], "exit_multiple": 11.0},
                "bull": {"fcf": [1.5], "ebitda_margin": [0.15], "capex": [0.08], "exit_multiple": 12.0},
            },
            "balance_ok": True,
        },
        "m7": {
            "rating": "BUY",
            "target_price": 250.0,
            "dcf_value": 240.0,
            "peer_multiple_value": 245.0,
            "model_id": "model-1",
            "reasoning": "Upside is supported by durable margin expansion.",
        },
        "m8": {
            "report_draft_md": "# Draft",
            "iteration": 1,
            "model_id": "model-1",
            "run_id": "run-1",
        },
        "m9": {
            "critic": "quant",
            "verdict": "PASS",
            "issues": [],
            "iteration": 1,
            "pipeline_run_id": "run-1",
        },
        "m10": {
            "report_final_md": "# Final",
            "disclosures_appended": True,
            "mnpi_clean": True,
            "rating_verified": True,
            "run_id": "run-1",
        },
        "m11": {
            "git_commit_hash": "abc123",
            "email_sent_at": "2026-05-22T01:00:00Z",
            "pdf_path": "/tmp/run-1.pdf",
            "run_id": "run-1",
        },
    }


def test_m1_valid():
    """Valid M1 payloads should round-trip via model_dump/model_validate."""

    payload = _valid_payloads()["m1"]
    model = M1TriggerEvent.model_validate(payload)
    assert model.model_dump() == payload
    assert M1TriggerEvent.model_validate(model.model_dump()) == model


def test_m2_confidence_out_of_range():
    """M2 confidence must stay within 0.0 and 1.0."""

    payload = _valid_payloads()["m2"]
    payload["confidence"] = 1.5
    with pytest.raises(ValidationError):
        M2MacroOutput.model_validate(payload)


def test_m7_invalid_rating():
    """M7 rating must be one of BUY, HOLD, SELL."""

    payload = _valid_payloads()["m7"]
    payload["rating"] = "STRONG BUY"
    with pytest.raises(ValidationError):
        M7ValuationOutput.model_validate(payload)


def test_m6_unbalanced_raises():
    """M6 must reject unbalanced models."""

    payload = _valid_payloads()["m6"]
    payload["balance_ok"] = False
    with pytest.raises(ValidationError):
        M6ModelOutput.model_validate(payload)


def test_m9_verdict_literals():
    """M9 verdict must be a constrained literal."""

    payload = _valid_payloads()["m9"]
    payload["verdict"] = "MAYBE"
    with pytest.raises(ValidationError):
        M9CritiqueVerdict.model_validate(payload)


def test_roundtrip_all_schemas():
    """Every schema should round-trip through dict serialization."""

    os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")
    os.environ.setdefault("AIDER_DATABASE_URL", "sqlite:///:memory:")
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
    os.environ.setdefault("FRED_API_KEY", "dummy")
    os.environ.setdefault("SEC_USER_AGENT", "Test User test@example.com")

    valid = _valid_payloads()
    schemas = [
        MessageEnvelope,
        M1TriggerEvent,
        M2MacroOutput,
        M3SectorOutput,
        M4ScreenOutput,
        M5DataOutput,
        M6ModelOutput,
        M7ValuationOutput,
        M8DraftReport,
        M9CritiqueVerdict,
        M10FinalReport,
        M11PublishReceipt,
    ]

    for schema in schemas:
        key = {
            MessageEnvelope: "envelope",
            M1TriggerEvent: "m1",
            M2MacroOutput: "m2",
            M3SectorOutput: "m3",
            M4ScreenOutput: "m4",
            M5DataOutput: "m5",
            M6ModelOutput: "m6",
            M7ValuationOutput: "m7",
            M8DraftReport: "m8",
            M9CritiqueVerdict: "m9",
            M10FinalReport: "m10",
            M11PublishReceipt: "m11",
        }[schema]
        obj = schema.model_validate(deepcopy(valid[key]))
        reconstructed = schema.model_validate(obj.model_dump())
        assert reconstructed == obj
