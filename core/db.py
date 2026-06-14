"""SQLAlchemy ORM models for the Aider database schema.

This module defines ORM mappings for all tables created by `db/schema.sql`.
It provides declarative model classes that other modules can import.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Boolean,
    Float,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for declarative models."""


class PipelineRun(Base):
    """ORM model for `pipeline_runs` table."""

    __tablename__ = "pipeline_runs"

    run_id: Mapped[Optional[str]] = mapped_column(Text, primary_key=True)
    ticker: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    git_commit_hash: Mapped[Optional[str]] = mapped_column(Text)


class DataPackage(Base):
    """ORM model for `data_packages` table."""

    __tablename__ = "data_packages"

    data_package_id: Mapped[Optional[str]] = mapped_column(Text, primary_key=True)
    run_id: Mapped[Optional[str]] = mapped_column(Text)
    ticker: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    payload: Mapped[Any] = mapped_column(JSONB, nullable=False)
    auditor_flags: Mapped[Any] = mapped_column(JSONB, default=list)


class FinancialModel(Base):
    """ORM model for `financial_models` table."""

    __tablename__ = "financial_models"

    model_id: Mapped[Optional[str]] = mapped_column(Text, primary_key=True)
    run_id: Mapped[Optional[str]] = mapped_column(Text)
    ticker: Mapped[str] = mapped_column(Text, nullable=False)
    built_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    wacc: Mapped[Optional[float]] = mapped_column(Numeric)
    scenarios: Mapped[Any] = mapped_column(JSONB, nullable=False)
    balance_ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    payload: Mapped[Any] = mapped_column(JSONB, nullable=False)
    sensitivity_table: Mapped[Any] = mapped_column(JSONB, nullable=True)


class Report(Base):
    """ORM model for `reports` table."""

    __tablename__ = "reports"

    report_id: Mapped[Optional[str]] = mapped_column(Text, primary_key=True)
    run_id: Mapped[Optional[str]] = mapped_column(Text)
    model_id: Mapped[Optional[str]] = mapped_column(Text)
    ticker: Mapped[str] = mapped_column(Text, nullable=False)
    iteration: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    draft_md: Mapped[Optional[str]] = mapped_column(Text)
    final_md: Mapped[Optional[str]] = mapped_column(Text)
    pdf_path: Mapped[Optional[str]] = mapped_column(Text)
    artifact_uri: Mapped[Optional[str]] = mapped_column(Text)
    rating: Mapped[Optional[str]] = mapped_column(Text)
    target_price: Mapped[Optional[float]] = mapped_column(Numeric)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class MacroRegime(Base):
    """ORM model for `macro_regime` table."""

    __tablename__ = "macro_regime"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    regime: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric, nullable=False)
    sector_overweights: Mapped[Any] = mapped_column(JSONB, nullable=False, default=list)
    sector_underweights: Mapped[Any] = mapped_column(JSONB, nullable=False, default=list)
    reasoning: Mapped[Optional[str]] = mapped_column(Text)
    classified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    """ORM model for `audit_log` table."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[Optional[str]] = mapped_column(Text)
    stage: Mapped[str] = mapped_column(Text, nullable=False)
    verdict: Mapped[Optional[str]] = mapped_column(Text)
    issues: Mapped[Any] = mapped_column(JSONB, default=list)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class DLQEntry(Base):
    """ORM model for `dlq_entries` table."""

    __tablename__ = "dlq_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[Optional[str]] = mapped_column(Text)
    stream: Mapped[str] = mapped_column(Text, nullable=False)
    message_id: Mapped[Optional[str]] = mapped_column(Text)
    reason: Mapped[Optional[str]] = mapped_column(Text)
    payload: Mapped[Any] = mapped_column(JSONB)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class LLMCall(Base):
    """ORM model for `llm_calls` table."""

    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[Optional[str]] = mapped_column(Text)
    agent: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[Optional[str]] = mapped_column(Text)
    prompt: Mapped[Any] = mapped_column(JSONB)
    response: Mapped[Any] = mapped_column(JSONB)
    confidence: Mapped[Optional[float]] = mapped_column(Numeric)
    cost_usd: Mapped[Optional[float]] = mapped_column(Numeric, default=0.0)
    input_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class CoverageUniverse(Base):
    """ORM model for `coverage_universe` table."""

    __tablename__ = "coverage_universe"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    added_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    notes: Mapped[Optional[str]] = mapped_column(Text)


class PriceSnapshot(Base):
    """ORM model for `price_snapshots` table."""

    __tablename__ = "price_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(Text, nullable=False)
    price: Mapped[float] = mapped_column(Numeric, nullable=False)
    snapped_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    source: Mapped[Optional[str]] = mapped_column(Text)


class EdgarTrigger(Base):
    """ORM model for `edgar_triggers` table."""

    __tablename__ = "edgar_triggers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    accession_number: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    run_id: Mapped[Optional[str]] = mapped_column(Text)
    ticker: Mapped[Optional[str]] = mapped_column(Text)
    form_type: Mapped[Optional[str]] = mapped_column(Text)
    fiscal_year: Mapped[Optional[int]] = mapped_column(Integer)
    fiscal_period: Mapped[Optional[str]] = mapped_column(Text)
    filed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


__all__ = [
    "Base",
    "PipelineRun",
    "DataPackage",
    "FinancialModel",
    "Report",
    "MacroRegime",
    "AuditLog",
    "DLQEntry",
    "LLMCall",
    "CoverageUniverse",
    "PriceSnapshot",
    "EdgarTrigger",
]
