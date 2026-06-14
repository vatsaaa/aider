"""Helpers for tracking EDGAR filings that have already triggered a run.

These helpers centralize the duplicate-check and insert logic for the
`edgar_triggers` table so the watcher can stay focused on feed processing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Engine, Connection, text

DatabaseHandle = Engine | Connection


def _connection(handle: DatabaseHandle):
    """Return a connection context from either an Engine or Connection."""

    return handle.begin() if isinstance(handle, Engine) else _nullcontext(handle)


class _nullcontext:
    """Minimal context manager for an already-open SQLAlchemy connection."""

    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def __enter__(self) -> Connection:
        return self.connection

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def already_triggered(handle: DatabaseHandle, accession_number: str) -> bool:
    """Return `True` when an accession number is already recorded."""

    with _connection(handle) as conn:
        row = conn.execute(
            text("SELECT 1 FROM edgar_triggers WHERE accession_number = :accession_number LIMIT 1"),
            {"accession_number": accession_number},
        ).fetchone()
    return row is not None


def already_triggered_for_period(
    handle: DatabaseHandle,
    *,
    ticker: str,
    form_type: str | None,
    fiscal_year: int | None,
    fiscal_period: str | None,
) -> bool:
    """Return `True` when the same ticker/form/fiscal period is already recorded."""

    if not ticker or not form_type or fiscal_year is None or not fiscal_period:
        return False

    with _connection(handle) as conn:
        row = conn.execute(
            text(
                "SELECT 1 FROM edgar_triggers "
                "WHERE ticker = :ticker AND form_type = :form_type "
                "AND fiscal_year = :fiscal_year AND fiscal_period = :fiscal_period LIMIT 1"
            ),
            {
                "ticker": ticker.upper(),
                "form_type": form_type,
                "fiscal_year": fiscal_year,
                "fiscal_period": fiscal_period,
            },
        ).fetchone()
    return row is not None


def record_trigger(
    handle: DatabaseHandle,
    accession_number: str,
    run_id: str | None,
    ticker: str | None,
    form_type: str | None,
    fiscal_year: int | None,
    fiscal_period: str | None,
    filed_at: datetime | None,
) -> bool:
    """Insert a trigger record if it does not already exist.

    Returns `True` when a new row was inserted and `False` if the accession
    number already existed.
    """

    with _connection(handle) as conn:
        result = conn.execute(
            text(
                "INSERT INTO edgar_triggers (accession_number, run_id, ticker, form_type, fiscal_year, fiscal_period, filed_at) "
                "VALUES (:accession_number, :run_id, :ticker, :form_type, :fiscal_year, :fiscal_period, :filed_at) "
                "ON CONFLICT DO NOTHING"
            ),
            {
                "accession_number": accession_number,
                "run_id": run_id,
                "ticker": ticker,
                "form_type": form_type,
                "fiscal_year": fiscal_year,
                "fiscal_period": fiscal_period,
                "filed_at": filed_at,
            },
        )
    return bool(getattr(result, "rowcount", 0))


def list_coverage_tickers(handle: DatabaseHandle) -> set[str]:
    """Return the current coverage universe as uppercase ticker symbols."""

    with _connection(handle) as conn:
        rows = conn.execute(text("SELECT ticker FROM coverage_universe")).fetchall()
    return {str(row[0]).upper() for row in rows if row and row[0]}


__all__ = ["already_triggered", "already_triggered_for_period", "record_trigger", "list_coverage_tickers"]