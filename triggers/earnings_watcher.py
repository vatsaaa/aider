"""Watcher that turns near-term earnings dates into trigger events.

The watcher scans the current coverage universe, checks each ticker's next
earnings date via yfinance, and publishes an M1 when earnings are within 24
hours. Duplicate alerts are suppressed with Redis TTL keys.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterator
from uuid import uuid4

from sqlalchemy import Connection, Engine, text

from core.bus import Bus
from core.config import Settings
from core.schemas import M1TriggerEvent, MessageEnvelope
from db.pipeline_runs import ensure_pipeline_run
import yfinance as yf


DatabaseHandle = Engine | Connection


@contextmanager
def _connection(handle: DatabaseHandle) -> Iterator[Connection]:
    """Yield a SQLAlchemy connection from either an engine or connection."""

    if isinstance(handle, Engine):
        with handle.begin() as connection:
            yield connection
    else:
        yield handle


class EarningsWatcher:
    """Poll the coverage universe for imminent earnings dates."""

    def __init__(self, bus: Bus, db: DatabaseHandle, settings: Settings) -> None:
        """Store runtime dependencies for polling and publishing."""

        self.bus = bus
        self.db = db
        self.settings = settings
        self.stream_name = "trigger:events"

    def poll(self) -> list[M1TriggerEvent]:
        """Publish an M1 for each covered ticker with earnings in the next day."""

        events: list[M1TriggerEvent] = []
        for ticker in self._covered_tickers():
            earnings_date = self._next_earnings_date(ticker)
            if earnings_date is None:
                continue

            if not self._is_within_24_hours(earnings_date):
                continue

            dedupe_key = self._dedupe_key(ticker, earnings_date)
            if not self._claim_dedupe_key(dedupe_key):
                continue

            event = M1TriggerEvent(
                ticker=ticker,
                trigger_type="earnings",
                pipeline_run_id=str(uuid4()),
            )
            ensure_pipeline_run(
                self.db,
                run_id=event.pipeline_run_id,
                ticker=event.ticker,
                trigger_type=event.trigger_type,
                status="started",
            )
            self._publish(event, earnings_date)
            events.append(event)

        return events

    def _covered_tickers(self) -> list[str]:
        """Return the current coverage universe tickers."""

        with _connection(self.db) as connection:
            rows = connection.execute(text("SELECT ticker FROM coverage_universe ORDER BY ticker")).fetchall()
        return [str(row[0]).upper() for row in rows if row and row[0]]

    def _next_earnings_date(self, ticker: str) -> datetime | None:
        """Extract the next earnings date from yfinance calendar data."""

        try:
            calendar = yf.Ticker(ticker).calendar
        except Exception:
            return None

        return self._coerce_calendar_date(calendar)

    def _coerce_calendar_date(self, calendar: Any) -> datetime | None:
        """Convert various yfinance calendar representations into a datetime."""

        candidate: Any = None
        if calendar is None:
            return None

        if isinstance(calendar, dict):
            for key in ("Earnings Date", "Earnings date", "earningsDate", "earnings_date"):
                if key in calendar:
                    candidate = calendar[key]
                    break
        elif hasattr(calendar, "loc") and hasattr(calendar, "empty"):
            try:
                if not calendar.empty:
                    candidate = calendar.iloc[0, 0]
            except Exception:
                candidate = None
        elif hasattr(calendar, "values"):
            values = getattr(calendar, "values")
            try:
                if len(values):
                    first_row = values[0]
                    candidate = first_row[0] if isinstance(first_row, (list, tuple)) else first_row
            except Exception:
                candidate = None
        elif hasattr(calendar, "__iter__"):
            try:
                candidate = next(iter(calendar))
            except StopIteration:
                candidate = None

        if isinstance(candidate, (list, tuple)):
            candidate = candidate[0] if candidate else None

        return self._normalize_datetime(candidate)

    def _normalize_datetime(self, value: Any) -> datetime | None:
        """Normalize a wide range of date-like inputs into a timezone-aware datetime."""

        if value is None:
            return None

        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

        if isinstance(value, date):
            return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)

        text_value = str(value).strip()
        if not text_value:
            return None

        normalized = text_value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    def _is_within_24_hours(self, earnings_date: datetime) -> bool:
        """Return True when the earnings date falls within the next 24 hours."""

        now = datetime.now(timezone.utc)
        delta = earnings_date - now
        return timedelta(0) <= delta <= timedelta(days=1)

    def _dedupe_key(self, ticker: str, earnings_date: datetime) -> str:
        """Build the Redis dedupe key for a ticker/date pair."""

        return f"earnings_triggered:{ticker}:{earnings_date.date().isoformat()}"

    def _claim_dedupe_key(self, key: str) -> bool:
        """Atomically claim a dedupe key with a 48-hour TTL."""

        redis_client = getattr(self.bus, "_client", None)
        if redis_client is None:
            return True

        result = redis_client.set(key, "1", ex=48 * 60 * 60, nx=True)
        return bool(result)

    def _publish(self, event: M1TriggerEvent, earnings_date: datetime) -> None:
        """Publish the M1 envelope to the trigger stream."""

        envelope = MessageEnvelope(
            message_id=str(uuid4()),
            pipeline_run_id=event.pipeline_run_id,
            trigger_type=event.trigger_type,
            ticker=event.ticker,
            timestamp=datetime.now(timezone.utc).isoformat(),
            payload=event.model_dump(),
            metadata={
                "source": "earnings_watcher",
                "earnings_date": earnings_date.isoformat(),
            },
        )
        self.bus.publish(self.stream_name, envelope.model_dump())

__all__ = ["EarningsWatcher"]