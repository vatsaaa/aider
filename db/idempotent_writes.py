"""Idempotent database write helpers for retry-safe pipeline stages.

These helpers implement a lookup-before-insert pattern keyed by `run_id` so
retrying a stage updates the existing logical row instead of creating a new
UUID-backed duplicate.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator
from uuid import uuid4

from sqlalchemy import Connection, Engine, inspect, text


DatabaseHandle = Engine | Connection


@contextmanager
def _connection(handle: DatabaseHandle) -> Iterator[Connection]:
    """Yield a SQLAlchemy connection from either an Engine or Connection."""

    if isinstance(handle, Engine):
        with handle.begin() as connection:
            yield connection
    else:
        yield handle


def _table_columns(handle: DatabaseHandle, table_name: str) -> set[str]:
    """Return the available column names for a table, or an empty set."""

    try:
        inspector = inspect(handle)
        if not inspector.has_table(table_name):
            return set()
        return {column["name"] for column in inspector.get_columns(table_name)}
    except Exception:
        return set()


def upsert_data_package(
    handle: DatabaseHandle,
    *,
    run_id: str,
    ticker: str,
    payload: Any,
    auditor_flags: Any,
    data_package_id: str | None = None,
    fetched_at: datetime | None = None,
) -> str:
    """Insert or update a data package row keyed by `run_id`.

    The helper reuses an existing `data_package_id` when a row for the same
    run already exists, otherwise it inserts a new row and returns the newly
    created identifier.
    """

    columns = _table_columns(handle, "data_packages")
    if not columns:
        return data_package_id or ""

    fetched_at = fetched_at or datetime.now(timezone.utc)
    with _connection(handle) as conn:
        existing = conn.execute(
            text(
                "SELECT data_package_id FROM data_packages WHERE run_id = :run_id "
                "ORDER BY fetched_at DESC, data_package_id DESC LIMIT 1"
            ),
            {"run_id": run_id},
        ).mappings().first()

        resolved_id = str(existing["data_package_id"]) if existing else (data_package_id or str(uuid4()))
        params = {
            "data_package_id": resolved_id,
            "run_id": run_id,
            "ticker": ticker,
            "fetched_at": fetched_at,
            "payload": payload,
            "auditor_flags": auditor_flags,
        }

        if existing is None:
            conn.execute(
                text(
                    "INSERT INTO data_packages (data_package_id, run_id, ticker, fetched_at, payload, auditor_flags) "
                    "VALUES (:data_package_id, :run_id, :ticker, :fetched_at, :payload, :auditor_flags)"
                ),
                params,
            )
        else:
            conn.execute(
                text(
                    "UPDATE data_packages SET ticker = :ticker, fetched_at = :fetched_at, payload = :payload, auditor_flags = :auditor_flags "
                    "WHERE data_package_id = :data_package_id"
                ),
                params,
            )

    return resolved_id


def upsert_financial_model(
    handle: DatabaseHandle,
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
    """Insert or update a financial model row keyed by `run_id`."""

    columns = _table_columns(handle, "financial_models")
    if not columns:
        return model_id or ""

    built_at = built_at or datetime.now(timezone.utc)
    with _connection(handle) as conn:
        existing = conn.execute(
            text(
                "SELECT model_id FROM financial_models WHERE run_id = :run_id "
                "ORDER BY built_at DESC, model_id DESC LIMIT 1"
            ),
            {"run_id": run_id},
        ).mappings().first()

        resolved_id = str(existing["model_id"]) if existing else (model_id or str(uuid4()))
        params = {
            "model_id": resolved_id,
            "run_id": run_id,
            "ticker": ticker,
            "built_at": built_at,
            "wacc": wacc,
            "scenarios": scenarios,
            "balance_ok": balance_ok,
            "payload": payload,
            "sensitivity_table": sensitivity_table,
        }

        if existing is None:
            conn.execute(
                text(
                    "INSERT INTO financial_models (model_id, run_id, ticker, built_at, wacc, scenarios, balance_ok, payload, sensitivity_table) "
                    "VALUES (:model_id, :run_id, :ticker, :built_at, :wacc, :scenarios, :balance_ok, :payload, :sensitivity_table)"
                ),
                params,
            )
        else:
            conn.execute(
                text(
                    "UPDATE financial_models SET ticker = :ticker, built_at = :built_at, wacc = :wacc, scenarios = :scenarios, balance_ok = :balance_ok, payload = :payload, sensitivity_table = :sensitivity_table "
                    "WHERE model_id = :model_id"
                ),
                params,
            )

    return resolved_id


def upsert_report(
    handle: DatabaseHandle,
    *,
    run_id: str,
    model_id: str,
    ticker: str,
    iteration: int,
    status: str,
    draft_md: str | None,
    final_md: str | None,
    rating: str | None,
    target_price: float | None,
    report_id: str | None = None,
    created_at: datetime | None = None,
) -> str:
    """Insert or update a report row keyed by `run_id`."""

    columns = _table_columns(handle, "reports")
    if not columns:
        return report_id or ""

    created_at = created_at or datetime.now(timezone.utc)
    with _connection(handle) as conn:
        existing = conn.execute(
            text(
                "SELECT report_id FROM reports WHERE run_id = :run_id "
                "ORDER BY created_at DESC, report_id DESC LIMIT 1"
            ),
            {"run_id": run_id},
        ).mappings().first()

        resolved_id = str(existing["report_id"]) if existing else (report_id or str(uuid4()))
        params = {
            "report_id": resolved_id,
            "run_id": run_id,
            "model_id": model_id,
            "ticker": ticker,
            "iteration": iteration,
            "status": status,
            "draft_md": draft_md,
            "final_md": final_md,
            "rating": rating,
            "target_price": target_price,
            "created_at": created_at,
        }

        if existing is None:
            conn.execute(
                text(
                    "INSERT INTO reports (report_id, run_id, model_id, ticker, iteration, status, draft_md, final_md, rating, target_price, created_at) "
                    "VALUES (:report_id, :run_id, :model_id, :ticker, :iteration, :status, :draft_md, :final_md, :rating, :target_price, :created_at)"
                ),
                params,
            )
        else:
            conn.execute(
                text(
                    "UPDATE reports SET model_id = :model_id, ticker = :ticker, iteration = :iteration, status = :status, "
                    "draft_md = :draft_md, final_md = :final_md, rating = :rating, target_price = :target_price, created_at = :created_at "
                    "WHERE report_id = :report_id"
                ),
                params,
            )

    return resolved_id


__all__ = ["upsert_data_package", "upsert_financial_model", "upsert_report"]
