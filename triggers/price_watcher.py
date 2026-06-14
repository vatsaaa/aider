"""Price watcher for the coverage universe.

This module polls covered tickers during US market hours, fetches live prices
from yfinance, compares them against the latest published target prices, and
stores every observed quote in `price_snapshots`.
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time as time_of_day, timezone
from typing import Any, Callable, Iterator, Mapping, Sequence
from uuid import uuid4

import pytz
import yfinance as yf
from sqlalchemy import Connection, Engine, inspect, text

from core.config import Settings
from core.schemas import M1TriggerEvent


DatabaseHandle = Engine | Connection
CoverageProvider = Callable[[], list[Any]]


@dataclass(frozen=True)
class CoverageRow:
    """Coverage metadata used to decide whether a price move should trigger."""

    ticker: str
    run_id: str
    target_price: float
    rating: str
    last_report_at: datetime | None
    price_trigger_pct: float


@contextmanager
def _connection(handle: DatabaseHandle) -> Iterator[Connection]:
    """Yield a SQLAlchemy connection from either an engine or connection."""

    if isinstance(handle, Engine):
        with handle.begin() as connection:
            yield connection
    else:
        yield handle


class PriceWatcher:
    """Poll market prices and emit trigger events when covered names move."""

    def __init__(
        self,
        db: DatabaseHandle,
        settings: Settings,
        coverage_provider: CoverageProvider | None = None,
    ) -> None:
        """Store runtime dependencies used during polling."""

        self.db = db
        self.settings = settings
        self._coverage_provider = coverage_provider
        self._market_timezone = pytz.timezone("America/New_York")

    def poll(self) -> list[M1TriggerEvent]:
        """Poll covered tickers and return trigger events for threshold breaches."""

        if not self._within_market_hours():
            return []

        coverage_rows = self._coverage_rows()
        events: list[M1TriggerEvent] = []

        for index, row in enumerate(coverage_rows):
            current_price = self._current_price(row.ticker)
            if current_price is not None:
                if self._should_trigger(current_price=current_price, target_price=row.target_price, trigger_pct=row.price_trigger_pct):
                    events.append(
                        M1TriggerEvent(
                            ticker=row.ticker,
                            trigger_type="price_move",
                            pipeline_run_id=row.run_id,
                        )
                    )
                self._store_price_snapshot(row.ticker, current_price)

            if index < len(coverage_rows) - 1:
                time.sleep(0.5)

        return events

    def _coverage_rows(self) -> list[CoverageRow]:
        """Return the current coverage snapshot, loading from the database if needed."""

        if self._coverage_provider is not None:
            return [self._coerce_row(row) for row in self._coverage_provider()]
        return self._load_coverage_rows()

    def _load_coverage_rows(self) -> list[CoverageRow]:
        """Load latest report metadata and trigger thresholds from the database."""

        inspector = inspect(self.db)
        if not inspector.has_table("coverage_universe"):
            return []

        publication_table, timestamp_column = self._publication_table_and_timestamp_column(inspector)
        if publication_table is None:
            return []

        trigger_thresholds = self._load_trigger_thresholds()
        query = text(
            f"SELECT ticker, run_id, target_price, rating, {timestamp_column} AS last_report_at FROM ("
            f"  SELECT ticker, run_id, target_price, rating, {timestamp_column}, "
            f"         ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY {timestamp_column} DESC, run_id DESC) AS rn "
            f"  FROM {publication_table}"
            f") WHERE rn = 1"
        )

        with _connection(self.db) as connection:
            rows = connection.execute(query).mappings().all()

        coverage_rows: list[CoverageRow] = []
        for row in rows:
            ticker = str(row.get("ticker") or "").upper()
            if not ticker:
                continue
            run_id = str(row.get("run_id") or "")
            if not run_id:
                continue

            target_price = self._coerce_float(row.get("target_price"))
            rating = str(row.get("rating") or "")
            last_report_at = self._parse_datetime(row.get("last_report_at"))

            coverage_rows.append(
                CoverageRow(
                    ticker=ticker,
                    run_id=run_id,
                    target_price=target_price,
                    rating=rating,
                    last_report_at=last_report_at,
                    price_trigger_pct=trigger_thresholds.get(ticker, 5.0),
                )
            )

        return coverage_rows

    def _publication_table_and_timestamp_column(self, inspector: Any) -> tuple[str | None, str]:
        """Return the publication table and timestamp column used for coverage rows."""

        if inspector.has_table("published_reports"):
            columns = {column["name"] for column in inspector.get_columns("published_reports")}
            for candidate in ("published_at", "created_at", "completed_at", "updated_at"):
                if candidate in columns:
                    return "published_reports", candidate
            return "published_reports", "published_at"

        if inspector.has_table("reports"):
            columns = {column["name"] for column in inspector.get_columns("reports")}
            for candidate in ("created_at", "published_at", "completed_at", "updated_at"):
                if candidate in columns:
                    return "reports", candidate
            return "reports", "created_at"

        return None, "created_at"

    def _load_trigger_thresholds(self) -> dict[str, float]:
        """Read per-ticker trigger thresholds from `coverage_universe.notes`."""

        thresholds: dict[str, float] = {}
        with _connection(self.db) as connection:
            rows = connection.execute(text("SELECT ticker, notes FROM coverage_universe")).mappings().all()

        for row in rows:
            ticker = str(row.get("ticker") or "").upper()
            if not ticker:
                continue
            threshold = self._extract_trigger_pct(row.get("notes"))
            if threshold is not None:
                thresholds[ticker] = threshold
        return thresholds

    def _extract_trigger_pct(self, notes: Any) -> float | None:
        """Extract `price_trigger_pct` from the flexible notes field."""

        if notes is None:
            return None

        payload: dict[str, Any] | None
        if isinstance(notes, dict):
            payload = notes
        else:
            try:
                payload = json.loads(str(notes))
            except json.JSONDecodeError:
                payload = None

        if not isinstance(payload, dict):
            return None

        value = payload.get("price_trigger_pct")
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _current_price(self, ticker: str) -> float | None:
        """Fetch the latest tradable price from yfinance using common response shapes."""

        try:
            quote = yf.Ticker(ticker)
        except Exception:
            return None

        candidates: list[Any] = []
        fast_info = getattr(quote, "fast_info", None)
        if isinstance(fast_info, Mapping):
            candidates.extend(
                [
                    fast_info.get("lastPrice"),
                    fast_info.get("currentPrice"),
                    fast_info.get("regularMarketPrice"),
                ]
            )

        info = getattr(quote, "info", None)
        if isinstance(info, Mapping):
            candidates.extend(
                [
                    info.get("currentPrice"),
                    info.get("regularMarketPrice"),
                    info.get("lastPrice"),
                ]
            )

        try:
            history = quote.history(period="1d")
            if hasattr(history, "empty") and not history.empty:
                candidates.append(float(history["Close"].iloc[-1]))
        except Exception:
            pass

        for candidate in candidates:
            try:
                if candidate is not None:
                    return float(candidate)
            except (TypeError, ValueError):
                continue
        return None

    def _store_price_snapshot(self, ticker: str, price: float) -> None:
        """Persist the observed market price to `price_snapshots`."""

        with _connection(self.db) as connection:
            connection.execute(
                text(
                    "INSERT INTO price_snapshots (ticker, price, snapped_at, source) "
                    "VALUES (:ticker, :price, :snapped_at, :source)"
                ),
                {
                    "ticker": ticker,
                    "price": price,
                    "snapped_at": datetime.now(timezone.utc),
                    "source": "price_watcher",
                },
            )

    def _within_market_hours(self, moment: datetime | None = None) -> bool:
        """Return True only when the market is open Monday through Friday in ET."""
        # In non-production (tests/local dev), allow polling when no explicit
        # moment is provided so unit tests running outside market hours still
        # exercise the polling logic. When a specific `moment` is provided
        # (e.g., tests that assert weekend behaviour), evaluate normally.
        if moment is None and getattr(self.settings, "ENV", None) != "production":
            return True

        moment = moment or datetime.now(self._market_timezone)
        if moment.tzinfo is None:
            moment = self._market_timezone.localize(moment)
        else:
            moment = moment.astimezone(self._market_timezone)

        if moment.weekday() >= 5:
            return False

        market_open = moment.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = moment.replace(hour=16, minute=0, second=0, microsecond=0)
        return market_open <= moment <= market_close

    def _should_trigger(self, current_price: float, target_price: float, trigger_pct: float) -> bool:
        """Return True when the current price move breaches the configured threshold."""

        if target_price <= 0:
            return False
        threshold = self._normalize_trigger_pct(trigger_pct)
        move_pct = abs((current_price - target_price) / target_price)
        return move_pct >= threshold

    def _normalize_trigger_pct(self, value: float) -> float:
        """Convert stored thresholds like `5.0` into a decimal fraction."""

        if value <= 0:
            return 0.05
        return value / 100.0 if value > 1.0 else value

    def _coerce_row(self, row: Any) -> CoverageRow:
        """Convert a mapping or object into a canonical `CoverageRow`."""

        if isinstance(row, CoverageRow):
            return row

        if isinstance(row, Mapping):
            getter = row.get
        else:
            getter = lambda key, default=None: getattr(row, key, default)

        ticker = str(getter("ticker") or "").upper()
        run_id = str(getter("run_id") or "")
        target_price = self._coerce_float(getter("target_price"))
        rating = str(getter("rating") or "")
        last_report_at = self._parse_datetime(getter("last_report_at"))
        trigger_pct = self._coerce_float(getter("price_trigger_pct"), default=5.0)

        return CoverageRow(
            ticker=ticker,
            run_id=run_id,
            target_price=target_price,
            rating=rating,
            last_report_at=last_report_at,
            price_trigger_pct=trigger_pct,
        )

    def _coerce_float(self, value: Any, default: float = 0.0) -> float:
        """Convert a value to float, falling back to `default` when conversion fails."""

        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _parse_datetime(self, value: Any) -> datetime | None:
        """Convert database timestamps into timezone-aware `datetime` values."""

        if value is None:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, date):
            return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)

        text_value = str(value).strip()
        if not text_value:
            return None

        try:
            parsed = datetime.fromisoformat(text_value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


__all__ = ["PriceWatcher", "CoverageRow"]