"""Watcher that promotes macro data releases from FRED into trigger events.

The watcher monitors a fixed set of macro series, stores the latest observed
value in `price_snapshots`, and emits an M1 trigger when a series changes.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Iterator
from uuid import uuid4

from sqlalchemy import Connection, Engine, text

from core.bus import Bus
from core.config import Settings
from core.schemas import M1TriggerEvent, MessageEnvelope
from db.pipeline_runs import ensure_pipeline_run
from fredapi import Fred


FRED_SERIES_IDS = (
    "FEDFUNDS",
    "DGS10",
    "DGS2",
    "CPIAUCSL",
    "PCEPI",
    "NAPM",
    "A191RL1Q225SBEA",
)


DatabaseHandle = Engine | Connection


@contextmanager
def _connection(handle: DatabaseHandle) -> Iterator[Connection]:
    """Yield a SQLAlchemy connection from either an engine or connection."""

    if isinstance(handle, Engine):
        with handle.begin() as connection:
            yield connection
    else:
        yield handle


class FredWatcher:
    """Poll FRED macro series and publish trigger events when values change."""

    def __init__(self, bus: Bus, db: DatabaseHandle, settings: Settings) -> None:
        """Store the runtime dependencies for polling and publishing."""

        self.bus = bus
        self.db = db
        self.settings = settings
        self.fred = Fred(api_key=settings.FRED_API_KEY)
        self.stream_name = "trigger:events"

    def poll(self) -> list[M1TriggerEvent]:
        """Check all monitored series and emit events for changed values."""

        events: list[M1TriggerEvent] = []
        for series_id in FRED_SERIES_IDS:
            latest_value = self._fetch_latest_value(series_id)
            if latest_value is None:
                continue

            current_value = self._latest_stored_value(series_id)
            self._store_value(series_id, latest_value)

            if current_value is None or self._values_differ(current_value, latest_value):
                event = M1TriggerEvent(
                    ticker="__MACRO__",
                    trigger_type="fred_release",
                    pipeline_run_id=str(uuid4()),
                )
                ensure_pipeline_run(
                    self.db,
                    run_id=event.pipeline_run_id,
                    ticker=event.ticker,
                    trigger_type=event.trigger_type,
                    status="started",
                )
                self._publish(event, series_id, latest_value)
                events.append(event)

        return events

    def _fetch_latest_value(self, series_id: str) -> float | None:
        """Fetch the most recent observation for a FRED series."""

        raw = self.fred.get_series(series_id)
        if raw is None:
            return None

        if hasattr(raw, "dropna"):
            cleaned = raw.dropna()
            if hasattr(cleaned, "iloc"):
                try:
                    value = cleaned.iloc[-1]
                except Exception:
                    value = None
            else:
                value = cleaned[-1] if len(cleaned) else None
        elif isinstance(raw, (list, tuple)):
            value = raw[-1] if raw else None
        else:
            value = raw

        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _latest_stored_value(self, series_id: str) -> float | None:
        """Return the latest stored snapshot value for a macro series."""

        ticker = self._snapshot_ticker(series_id)
        with _connection(self.db) as connection:
            row = connection.execute(
                text(
                    "SELECT price FROM price_snapshots "
                    "WHERE ticker = :ticker ORDER BY snapped_at DESC, id DESC LIMIT 1"
                ),
                {"ticker": ticker},
            ).fetchone()

        if row is None or row[0] is None:
            return None
        try:
            return float(row[0])
        except (TypeError, ValueError):
            return None

    def _store_value(self, series_id: str, value: float) -> None:
        """Persist the current value to the price snapshots table."""

        ticker = self._snapshot_ticker(series_id)
        with _connection(self.db) as connection:
            connection.execute(
                text(
                    "INSERT INTO price_snapshots (ticker, price, snapped_at, source) "
                    "VALUES (:ticker, :price, :snapped_at, :source)"
                ),
                {
                    "ticker": ticker,
                    "price": value,
                    "snapped_at": datetime.now(timezone.utc),
                    "source": "fred",
                },
            )

    def _publish(self, event: M1TriggerEvent, series_id: str, value: float) -> None:
        """Publish the M1 envelope for a changed macro series."""

        envelope = MessageEnvelope(
            message_id=str(uuid4()),
            pipeline_run_id=event.pipeline_run_id,
            trigger_type=event.trigger_type,
            ticker=event.ticker,
            timestamp=datetime.now(timezone.utc).isoformat(),
            payload=event.model_dump(),
            metadata={
                "source": "fred_watcher",
                "series_id": series_id,
                "series_value": value,
            },
        )
        self.bus.publish(self.stream_name, envelope.model_dump())

    def _snapshot_ticker(self, series_id: str) -> str:
        """Return the snapshot ticker used to store a series value."""

        return f"__MACRO__:{series_id}"

    def _values_differ(self, stored: float, latest: float) -> bool:
        """Compare numeric values with a small tolerance for floating noise."""

        return abs(float(Decimal(str(stored)) - Decimal(str(latest)))) > 1e-9


__all__ = ["FredWatcher", "FRED_SERIES_IDS"]