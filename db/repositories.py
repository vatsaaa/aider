"""ORM-backed repository helpers for pipeline agents.

The repository centralizes reads and writes that used to live directly inside
agent `process()` methods. It uses the declarative models from `core.db` so
callers stay isolated from SQL text and dialect-specific details.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator
from uuid import uuid4

from sqlalchemy import MetaData, Table, desc, inspect, insert, select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.types import JSON as SAJSON

from core.db import CoverageUniverse, DataPackage, FinancialModel, MacroRegime, PipelineRun, Report


DatabaseHandle = Engine | Connection | Session


@contextmanager
def _session(handle: DatabaseHandle) -> Iterator[Session]:
    """Yield a session bound to an engine, connection, or existing session."""

    if isinstance(handle, Session):
        yield handle
        return

    session = Session(bind=handle)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _bind(handle: DatabaseHandle) -> Engine | Connection | Session:
    """Return the bind that should be inspected for table availability."""

    if isinstance(handle, Session):
        bind = handle.get_bind()
        return bind if bind is not None else handle
    return handle


def _has_table(handle: DatabaseHandle, table_name: str) -> bool:
    """Return whether the current bind exposes `table_name`."""

    try:
        return inspect(_bind(handle)).has_table(table_name)
    except Exception:
        return False


def _model_dict(instance: Any) -> dict[str, Any]:
    """Convert a mapped ORM instance into a plain dictionary."""

    if instance is None:
        return {}
    data: dict[str, Any] = {}
    for column in instance.__mapper__.column_attrs:
        data[column.key] = getattr(instance, column.key)
    return data


def _json_value(value: Any) -> Any:
    """Normalize stored JSON payloads that may already be Python objects."""

    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return value
    return value


def _table_columns(handle: DatabaseHandle, table_name: str) -> set[str]:
    """Return the available columns for a table."""

    try:
        return {column["name"] for column in inspect(_bind(handle)).get_columns(table_name)}
    except Exception:
        return set()


def _select_mapping(
    handle: DatabaseHandle,
    model: Any,
    table_name: str,
    column_names: list[str],
    *,
    where_clause: Any = None,
    order_by: list[Any] | None = None,
) -> dict[str, Any] | None:
    """Select a single row using only columns that exist on the current table."""

    available = _table_columns(handle, table_name)
    selected_columns = [getattr(model, name) for name in column_names if name in available and hasattr(model, name)]
    if not selected_columns:
        return None

    with _session(handle) as session:
        statement = select(*selected_columns)
        if where_clause is not None:
            statement = statement.where(where_clause)
        if order_by:
            statement = statement.order_by(*order_by)
        try:
            row = session.execute(statement).mappings().first()
        except Exception:
            fallback = select(*selected_columns)
            if where_clause is not None:
                fallback = fallback.where(where_clause)
            row = session.execute(fallback).mappings().first()
    return dict(row) if row is not None else None


def _filter_values(handle: DatabaseHandle, table_name: str, values: dict[str, Any]) -> dict[str, Any]:
    """Keep only values for columns that are actually present on the table."""

    available = _table_columns(handle, table_name)
    return {key: value for key, value in values.items() if key in available}


def _reflected_table(handle: DatabaseHandle, table_name: str) -> Table | None:
    """Reflect the current table schema from the live database."""

    try:
        metadata = MetaData()
        return Table(table_name, metadata, autoload_with=_bind(handle))
    except Exception:
        return None


def _store_json_value(table: Table, column_name: str, value: Any) -> Any:
    """Serialize a value only when the reflected column is text-based."""

    column = table.c.get(column_name)
    if column is None:
        return value
    if isinstance(column.type, SAJSON):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return value


class AgentRepository:
    """Repository for the common agent persistence and lookup operations."""

    def __init__(self, handle: DatabaseHandle | None) -> None:
        self._handle = handle

    def ensure_pipeline_run(
        self,
        *,
        run_id: str | None,
        ticker: str | None = None,
        trigger_type: str | None = None,
        status: str = "started",
    ) -> bool:
        """Insert a pipeline run row if it is missing."""

        if self._handle is None or not run_id or not _has_table(self._handle, "pipeline_runs"):
            return False

        with _session(self._handle) as session:
            existing = session.execute(
                select(PipelineRun.run_id).where(PipelineRun.run_id == run_id).limit(1)
            ).first()
            if existing is not None:
                return True

            values = _filter_values(
                self._handle,
                "pipeline_runs",
                {
                    "run_id": run_id,
                    "ticker": ticker or "",
                    "trigger_type": trigger_type or "manual",
                    "status": status,
                    "started_at": datetime.now(timezone.utc),
                },
            )
            session.execute(insert(PipelineRun.__table__).values(**values))
        return True

    def load_pipeline_run_ticker(self, run_id: str | None) -> str | None:
        """Return the ticker stored on the pipeline run row."""

        if self._handle is None or not run_id or not _has_table(self._handle, "pipeline_runs"):
            return None

        row = _select_mapping(
            self._handle,
            PipelineRun,
            "pipeline_runs",
            ["ticker"],
            where_clause=PipelineRun.run_id == run_id,
        )
        return row.get("ticker") if row else None

    def coverage_tickers_for_sector(self, sector: str) -> list[str]:
        """Return coverage-universe tickers tagged for the given sector."""

        if self._handle is None or not _has_table(self._handle, "coverage_universe"):
            return []

        tickers: list[str] = []
        with _session(self._handle) as session:
            rows = session.execute(select(CoverageUniverse.ticker, CoverageUniverse.notes)).all()

        for ticker, notes in rows:
            parsed_notes = _json_value(notes)
            if isinstance(parsed_notes, dict) and parsed_notes.get("sector") == sector:
                tickers.append(str(ticker))
        return tickers

    def load_latest_macro_regime(self) -> dict[str, Any] | None:
        """Return the latest persisted macro regime classification."""

        if self._handle is None or not _has_table(self._handle, "macro_regime"):
            return None

        row = _select_mapping(
            self._handle,
            MacroRegime,
            "macro_regime",
            ["id", "regime", "confidence", "sector_overweights", "sector_underweights", "reasoning", "classified_at"],
            order_by=[desc(MacroRegime.classified_at), desc(MacroRegime.id)],
        )
        if row is None:
            return None

        row["sector_overweights"] = _json_value(row.get("sector_overweights"))
        row["sector_underweights"] = _json_value(row.get("sector_underweights"))
        return row

    def save_macro_regime(
        self,
        *,
        regime: str,
        confidence: float,
        sector_overweights: Any,
        sector_underweights: Any,
        reasoning: str | None,
        classified_at: datetime | None = None,
    ) -> None:
        """Persist a macro regime classification row."""

        if self._handle is None or not _has_table(self._handle, "macro_regime"):
            return

        values = _filter_values(
            self._handle,
            "macro_regime",
            {
                "regime": regime,
                "confidence": confidence,
                "sector_overweights": sector_overweights,
                "sector_underweights": sector_underweights,
                "reasoning": reasoning,
                "classified_at": classified_at or datetime.now(timezone.utc),
            },
        )
        with _session(self._handle) as session:
            session.execute(insert(MacroRegime.__table__).values(**values))

    def load_data_package_by_id(self, data_package_id: str) -> dict[str, Any] | None:
        """Load a data package by primary key."""

        if self._handle is None or not _has_table(self._handle, "data_packages"):
            return None

        row = _select_mapping(
            self._handle,
            DataPackage,
            "data_packages",
            ["data_package_id", "run_id", "ticker", "fetched_at", "payload", "auditor_flags"],
            where_clause=DataPackage.data_package_id == data_package_id,
        )
        if row is None:
            return None

        row["payload"] = _json_value(row.get("payload"))
        row["auditor_flags"] = _json_value(row.get("auditor_flags"))
        return row

    def load_latest_data_package_by_run_id(self, run_id: str) -> dict[str, Any] | None:
        """Load the most recent data package for a pipeline run."""

        table = _reflected_table(self._handle, "data_packages") if self._handle is not None else None
        if table is None:
            return None

        column_names = list(table.c.keys())
        row = _select_mapping(
            self._handle,
            DataPackage,
            "data_packages",
            [name for name in ["data_package_id", "run_id", "ticker", "fetched_at", "payload", "auditor_flags"] if name in column_names],
            where_clause=DataPackage.run_id == run_id,
            order_by=[desc(getattr(DataPackage, "fetched_at")), desc(getattr(DataPackage, "data_package_id"))] if "fetched_at" in column_names and "data_package_id" in column_names else None,
        )
        if row is None:
            return None

        row["payload"] = _json_value(row.get("payload"))
        row["auditor_flags"] = _json_value(row.get("auditor_flags"))
        return row

    def load_data_package(self, run_id: str) -> dict[str, Any] | None:
        """Compatibility alias for the latest data package lookup."""

        return self.load_latest_data_package_by_run_id(run_id)

    def save_data_package(
        self,
        *,
        run_id: str,
        ticker: str,
        payload: Any,
        auditor_flags: Any,
        data_package_id: str | None = None,
        fetched_at: datetime | None = None,
    ) -> str:
        """Insert or update a data package keyed by `run_id`."""

        table = _reflected_table(self._handle, "data_packages") if self._handle is not None else None
        if table is None:
            return data_package_id or ""

        fetched_at = fetched_at or datetime.now(timezone.utc)
        existing = self.load_latest_data_package_by_run_id(run_id)
        resolved_id = str(existing.get("data_package_id")) if existing is not None else (data_package_id or str(uuid4()))
        available = set(table.c.keys())
        values: dict[str, Any] = {
            "data_package_id": resolved_id,
            "run_id": run_id,
            "ticker": ticker,
            "fetched_at": fetched_at,
            "payload": _store_json_value(table, "payload", payload),
        }
        if "auditor_flags" in available:
            values["auditor_flags"] = _store_json_value(table, "auditor_flags", auditor_flags)
        with _session(self._handle) as session:
            try:
                if existing is None:
                    session.execute(insert(table).values(**values))
                else:
                    session.execute(
                        update(table).where(table.c.data_package_id == resolved_id).values(**values)
                    )
            except SQLAlchemyError as error:
                if "auditor_flags" not in str(error):
                    raise
                trimmed = dict(values)
                trimmed.pop("auditor_flags", None)
                if existing is None:
                    session.execute(insert(table).values(**trimmed))
                else:
                    session.execute(
                        update(table).where(table.c.data_package_id == resolved_id).values(**trimmed)
                    )

        return resolved_id

    def load_financial_model_by_id(self, model_id: str) -> dict[str, Any] | None:
        """Load a financial model row by primary key."""

        if self._handle is None or not _has_table(self._handle, "financial_models"):
            return None

        row = _select_mapping(
            self._handle,
            FinancialModel,
            "financial_models",
            ["model_id", "run_id", "ticker", "built_at", "wacc", "scenarios", "balance_ok", "payload", "sensitivity_table"],
            where_clause=FinancialModel.model_id == model_id,
        )
        if row is None:
            return None

        row["payload"] = _json_value(row.get("payload"))
        row["scenarios"] = _json_value(row.get("scenarios"))
        row["sensitivity_table"] = _json_value(row.get("sensitivity_table"))
        return row

    def load_latest_financial_model_by_run_id(self, run_id: str) -> dict[str, Any] | None:
        """Load the newest financial model row for the pipeline run."""

        if self._handle is None or not _has_table(self._handle, "financial_models"):
            return None

        row = _select_mapping(
            self._handle,
            FinancialModel,
            "financial_models",
            ["model_id", "run_id", "ticker", "built_at", "wacc", "scenarios", "balance_ok", "payload", "sensitivity_table"],
            where_clause=FinancialModel.run_id == run_id,
            order_by=[desc(FinancialModel.built_at), desc(FinancialModel.model_id)],
        )
        if row is None:
            return None

        row["payload"] = _json_value(row.get("payload"))
        row["scenarios"] = _json_value(row.get("scenarios"))
        row["sensitivity_table"] = _json_value(row.get("sensitivity_table"))
        return row

    def save_financial_model(
        self,
        *,
        run_id: str,
        ticker: str,
        payload: Any,
        scenarios: Any,
        balance_ok: bool,
        wacc: float | None = None,
        sensitivity_table: Any = None,
        model_id: str | None = None,
        built_at: datetime | None = None,
    ) -> str:
        """Insert or update a financial model keyed by `run_id`."""

        if self._handle is None or not _has_table(self._handle, "financial_models"):
            return model_id or ""

        built_at = built_at or datetime.now(timezone.utc)
        existing = self.load_latest_financial_model_by_run_id(run_id)
        resolved_id = str(existing.get("model_id")) if existing is not None else (model_id or str(uuid4()))
        values = _filter_values(
            self._handle,
            "financial_models",
            {
                "model_id": resolved_id,
                "run_id": run_id,
                "ticker": ticker,
                "built_at": built_at,
                "wacc": wacc,
                "scenarios": scenarios,
                "balance_ok": balance_ok,
                "payload": payload,
                "sensitivity_table": sensitivity_table,
            },
        )
        with _session(self._handle) as session:
            if existing is None:
                session.execute(insert(FinancialModel.__table__).values(**values))
            else:
                session.execute(
                    update(FinancialModel.__table__).where(FinancialModel.__table__.c.model_id == resolved_id).values(**values)
                )

        return resolved_id

    def update_financial_model_valuation(
        self,
        *,
        model_id: str,
        payload: Any,
        sensitivity_table: Any,
    ) -> bool:
        """Update the stored valuation payload and sensitivity table."""

        if self._handle is None or not _has_table(self._handle, "financial_models"):
            return False

        values = _filter_values(
            self._handle,
            "financial_models",
            {
                "payload": payload,
                "sensitivity_table": sensitivity_table,
            },
        )
        with _session(self._handle) as session:
            result = session.execute(
                update(FinancialModel.__table__).where(FinancialModel.__table__.c.model_id == model_id).values(**values)
            )
            if result.rowcount == 0:
                return False
        return True

    def load_report_by_run_id(self, run_id: str) -> dict[str, Any] | None:
        """Load the latest report row for a run."""

        if self._handle is None or not _has_table(self._handle, "reports"):
            return None

        row = _select_mapping(
            self._handle,
            Report,
            "reports",
            ["report_id", "run_id", "model_id", "ticker", "iteration", "status", "draft_md", "final_md", "pdf_path", "artifact_uri", "rating", "target_price", "created_at"],
            where_clause=Report.run_id == run_id,
            order_by=[desc(Report.created_at), desc(Report.report_id)],
        )
        if row is None:
            return None

        return row

    def update_report_final(
        self,
        *,
        run_id: str,
        final_md: str,
        status: str = "approved",
    ) -> bool:
        """Update the stored report markdown and status for a run."""

        if self._handle is None or not _has_table(self._handle, "reports"):
            return False

        values = _filter_values(
            self._handle,
            "reports",
            {
                "status": status,
                "final_md": final_md,
            },
        )
        with _session(self._handle) as session:
            result = session.execute(
                update(Report.__table__).where(Report.__table__.c.run_id == run_id).values(**values)
            )
            if result.rowcount == 0:
                return False
        return True

    def update_report_artifacts(
        self,
        *,
        run_id: str,
        pdf_path: str | None = None,
        artifact_uri: str | None = None,
    ) -> bool:
        """Persist the local PDF path and optional object-store URI for a report."""

        if self._handle is None or not _has_table(self._handle, "reports"):
            return False

        values = _filter_values(
            self._handle,
            "reports",
            {
                "pdf_path": pdf_path,
                "artifact_uri": artifact_uri,
            },
        )
        if not values:
            return False

        with _session(self._handle) as session:
            result = session.execute(
                update(Report.__table__).where(Report.__table__.c.run_id == run_id).values(**values)
            )
            if result.rowcount == 0:
                return False
        return True

    def update_pipeline_run_status(
        self,
        *,
        run_id: str,
        status: str,
        git_commit_hash: str | None = None,
        completed_at: datetime | None = None,
    ) -> bool:
        """Update the pipeline run status after successful publication."""

        if self._handle is None or not _has_table(self._handle, "pipeline_runs"):
            return False

        values = _filter_values(
            self._handle,
            "pipeline_runs",
            {
                "status": status,
                "git_commit_hash": git_commit_hash,
                "completed_at": completed_at,
            },
        )
        with _session(self._handle) as session:
            result = session.execute(
                update(PipelineRun.__table__).where(PipelineRun.__table__.c.run_id == run_id).values(**values)
            )
            if result.rowcount == 0:
                return False
        return True


__all__ = ["AgentRepository"]