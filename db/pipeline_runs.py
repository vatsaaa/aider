"""Idempotent helpers for creating and managing pipeline run rows.

The trigger layer and base agent both use these helpers to ensure the parent
`pipeline_runs` row exists before downstream stages attempt foreign-keyed
inserts. The insert is safe to call repeatedly thanks to `ON CONFLICT`.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

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


def ensure_pipeline_run(
    handle: DatabaseHandle | None,
    *,
    run_id: str | None,
    ticker: str | None = None,
    trigger_type: str | None = None,
    status: str = "started",
) -> bool:
    """Insert a `pipeline_runs` row if the table exists and the run is missing.

    The helper inspects the table schema and only includes columns that are
    present. This keeps the behavior compatible with both the production
    schema and the lightweight test tables used throughout the suite.

    Returns `True` when the insert was attempted and `False` when the table is
    unavailable or the run identifier is missing.
    """

    if handle is None or not run_id:
        return False

    try:
        inspector = inspect(handle)
        if not inspector.has_table("pipeline_runs"):
            return False
        columns = {column["name"] for column in inspector.get_columns("pipeline_runs")}
    except Exception:
        return False

    values: dict[str, Any] = {"run_id": run_id}
    insert_columns: list[str] = ["run_id"]

    if "ticker" in columns:
        values["ticker"] = ticker or ""
        insert_columns.append("ticker")
    if "trigger_type" in columns:
        values["trigger_type"] = trigger_type or "manual"
        insert_columns.append("trigger_type")
    if "status" in columns:
        values["status"] = status
        insert_columns.append("status")
    if "started_at" in columns:
        values["started_at"] = datetime.now(timezone.utc)
        insert_columns.append("started_at")

    placeholders = ", ".join(f":{column}" for column in insert_columns)
    statement = text(
        f"INSERT INTO pipeline_runs ({', '.join(insert_columns)}) "
        f"VALUES ({placeholders}) ON CONFLICT (run_id) DO NOTHING"
    )

    with _connection(handle) as connection:
        connection.execute(statement, values)
    return True


__all__ = ["ensure_pipeline_run"]
