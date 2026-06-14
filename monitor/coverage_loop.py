"""Coverage monitor daemon.

This module keeps completed coverage live after publication. It loads the
latest published research per ticker, re-triggers the pipeline when a covered
name moves outside its configured threshold, and sends a weekly digest email
with current market prices and report metadata.
"""

from __future__ import annotations

import json
import smtplib
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Callable, Iterator, Optional
from uuid import uuid4

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import Connection, Engine, inspect, text

import yfinance as yf

from core.bus import Bus
from core.config import Settings
from core.schemas import M1TriggerEvent, MessageEnvelope
from db.pipeline_runs import ensure_pipeline_run


DatabaseHandle = Engine | Connection


@dataclass(frozen=True)
class CoverageRow:
    """Coverage metadata used by price polling and digest generation."""

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
    """Poll current market prices and turn threshold moves into M1 events."""

    def __init__(self, db: DatabaseHandle, settings: Settings, coverage_provider: Callable[[], list[CoverageRow]]) -> None:
        """Store dependencies for price polling."""

        self.db = db
        self.settings = settings
        self._coverage_provider = coverage_provider

    def poll(self) -> list[M1TriggerEvent]:
        """Return M1 events for tickers that have moved outside the threshold."""

        events: list[M1TriggerEvent] = []
        for row in self._coverage_provider():
            current_price = self._current_price(row.ticker)
            if current_price is None:
                continue

            trigger_pct = self._normalise_trigger_pct(row.price_trigger_pct)
            target_price = float(row.target_price)
            if target_price <= 0:
                self._store_price_snapshot(row.ticker, current_price)
                continue

            move_pct = abs((current_price - target_price) / target_price)
            if move_pct >= trigger_pct:
                events.append(
                    M1TriggerEvent(
                        ticker=row.ticker,
                        trigger_type="manual",
                        pipeline_run_id=row.run_id,
                    )
                )

            self._store_price_snapshot(row.ticker, current_price)

        return events

    def _normalise_trigger_pct(self, value: float) -> float:
        """Convert stored thresholds like 5.0 into a 0.05 fraction."""

        if value <= 0:
            return 0.05
        return value / 100.0 if value > 1.0 else value

    def _current_price(self, ticker: str) -> float | None:
        """Fetch the latest price from yfinance using several common shapes."""

        try:
            quote = yf.Ticker(ticker)
        except Exception:
            return None

        candidates: list[Any] = []
        for attr in ("fast_info", "info"):
            value = getattr(quote, attr, None)
            if isinstance(value, dict):
                candidates.extend([value.get("lastPrice"), value.get("currentPrice"), value.get("regularMarketPrice")])

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
                    "VALUES (:ticker, :price, CURRENT_TIMESTAMP, :source)"
                ),
                {"ticker": ticker, "price": price, "source": "coverage_monitor"},
            )


class CoverageMonitor:
    """Daemon that keeps published research live and monitored for moves."""

    def __init__(
        self,
        bus: Bus,
        db: DatabaseHandle,
        settings: Settings,
        price_watcher: PriceWatcher | None = None,
        smtp_factory: Callable[[str, int], smtplib.SMTP] = smtplib.SMTP,
    ) -> None:
        """Store runtime dependencies and prime the in-memory coverage cache."""

        self.bus = bus
        self.db = db
        self.settings = settings
        self._smtp_factory = smtp_factory
        self._coverage: list[CoverageRow] = []
        self.scheduler = BackgroundScheduler(timezone="America/New_York")
        self.price_watcher = price_watcher or PriceWatcher(db=db, settings=settings, coverage_provider=self.coverage_rows)
        self.refresh_coverage()

    def refresh_coverage(self) -> list[CoverageRow]:
        """Reload the latest completed runs and their publication metadata."""

        complete_runs = self._load_latest_completed_runs()
        publication_rows = self._load_publication_rows()
        trigger_map = self._load_trigger_thresholds()

        covered: list[CoverageRow] = []
        for row in complete_runs:
            ticker = row["ticker"]
            publication = publication_rows.get(ticker)
            if publication is None:
                continue

            covered.append(
                CoverageRow(
                    ticker=ticker,
                    run_id=str(row["run_id"]),
                    target_price=float(publication["target_price"] or 0.0),
                    rating=str(publication["rating"] or ""),
                    last_report_at=publication.get("last_report_at"),
                    price_trigger_pct=float(trigger_map.get(ticker, 5.0)),
                )
            )

        self._coverage = covered
        return list(self._coverage)

    def coverage_rows(self) -> list[CoverageRow]:
        """Return the cached coverage snapshot."""

        return list(self._coverage)

    def start(self) -> None:
        """Register APScheduler jobs and start the daemon."""

        self.scheduler.add_job(self.poll_price_moves, IntervalTrigger(hours=4), id="coverage_price_poll")
        self.scheduler.add_job(self.send_weekly_digest, CronTrigger(day_of_week="mon", hour=6, minute=0), id="coverage_weekly_digest")
        self.scheduler.start()

    def run(self) -> None:
        """Block forever after starting the scheduler."""

        self.start()
        try:
            while True:
                pass
        except KeyboardInterrupt:
            self.scheduler.shutdown(wait=False)

    def poll_price_moves(self) -> list[M1TriggerEvent]:
        """Run the price watcher and publish any generated M1 events."""

        self.refresh_coverage()
        events = self.price_watcher.poll()
        for event in events:
            self._publish_m1(event)
        return events

    def send_weekly_digest(self) -> str:
        """Build and send the weekly markdown digest email."""

        self.refresh_coverage()
        rows: list[str] = ["# Weekly Coverage Digest", ""]
        rows.append("| Ticker | Current Price | Target Price | Rating | Upside/Downside % | Days Since Last Report |")
        rows.append("| --- | ---: | ---: | --- | ---: | ---: |")

        for row in self._coverage:
            current_price = self._current_price(row.ticker)
            if current_price is None:
                continue

            upside_pct = 0.0
            if row.target_price > 0:
                upside_pct = ((current_price - row.target_price) / row.target_price) * 100.0

            days_since = self._days_since(row.last_report_at)
            rows.append(
                f"| {row.ticker} | ${current_price:,.2f} | ${row.target_price:,.2f} | {row.rating} | {upside_pct:+.1f}% | {days_since} |"
            )

        body = "\n".join(rows)
        self._send_email(subject="Weekly Coverage Digest", body=body)
        return body

    def _current_price(self, ticker: str) -> float | None:
        """Delegate current-price lookup to the watcher implementation."""

        return self.price_watcher._current_price(ticker)

    def _load_latest_completed_runs(self) -> list[dict[str, Any]]:
        """Load the newest completed run per ticker from `pipeline_runs`."""

        query = text(
            "SELECT ticker, run_id, completed_at FROM ("
            "  SELECT ticker, run_id, completed_at, "
            "         ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY COALESCE(completed_at, started_at) DESC, run_id DESC) AS rn "
            "  FROM pipeline_runs WHERE status = 'complete'"
            ") WHERE rn = 1"
        )

        with _connection(self.db) as connection:
            rows = connection.execute(query).mappings().all()

        return [dict(row) for row in rows]

    def _load_publication_rows(self) -> dict[str, dict[str, Any]]:
        """Load latest publication metadata from `published_reports` or `reports`."""

        table_name, timestamp_column = self._publication_table_name_and_timestamp_column()
        query = text(
            f"SELECT ticker, run_id, target_price, rating, {timestamp_column} AS last_report_at FROM ("
            f"  SELECT ticker, run_id, target_price, rating, {timestamp_column}, "
            f"         ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY {timestamp_column} DESC, run_id DESC) AS rn "
            f"  FROM {table_name}"
            f") WHERE rn = 1"
        )

        with _connection(self.db) as connection:
            rows = connection.execute(query).mappings().all()

        publications: dict[str, dict[str, Any]] = {}
        for row in rows:
            publications[str(row["ticker"])]= {
                "run_id": row.get("run_id"),
                "target_price": row.get("target_price"),
                "rating": row.get("rating"),
                "last_report_at": self._parse_datetime(row.get("last_report_at")),
            }
        return publications

    def _publication_table_name_and_timestamp_column(self) -> tuple[str, str]:
        """Return the publication table and timestamp column to query."""

        inspector = inspect(self.db)
        if inspector.has_table("published_reports"):
            columns = {column["name"] for column in inspector.get_columns("published_reports")}
            for candidate in ("published_at", "created_at", "completed_at", "updated_at"):
                if candidate in columns:
                    return "published_reports", candidate
            return "published_reports", "published_at"

        columns = {column["name"] for column in inspector.get_columns("reports")}
        for candidate in ("created_at", "published_at", "completed_at", "updated_at"):
            if candidate in columns:
                return "reports", candidate
        return "reports", "created_at"

    def _load_trigger_thresholds(self) -> dict[str, float]:
        """Read per-ticker threshold settings from `coverage_universe`."""

        thresholds: dict[str, float] = {}
        with _connection(self.db) as connection:
            rows = connection.execute(text("SELECT ticker, notes FROM coverage_universe")).mappings().all()

        for row in rows:
            ticker = str(row.get("ticker") or "").upper()
            if not ticker:
                continue
            notes = row.get("notes")
            threshold = self._extract_trigger_pct(notes)
            if threshold is not None:
                thresholds[ticker] = threshold
        return thresholds

    def _extract_trigger_pct(self, notes: Any) -> float | None:
        """Pull `price_trigger_pct` from the flexible `coverage_universe.notes` field."""

        if notes is None:
            return None

        payload: dict[str, Any] | None = None
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

    def _publish_m1(self, event: M1TriggerEvent) -> None:
        """Publish a trigger event onto the shared trigger stream."""

        ensure_pipeline_run(
            self.db,
            run_id=event.pipeline_run_id,
            ticker=event.ticker,
            trigger_type=event.trigger_type,
            status="started",
        )
        envelope = MessageEnvelope(
            message_id=str(uuid4()),
            pipeline_run_id=event.pipeline_run_id,
            trigger_type=event.trigger_type,
            ticker=event.ticker,
            timestamp=datetime.now(timezone.utc).isoformat(),
            payload=event.model_dump(),
            metadata={"source": "coverage_monitor"},
        )
        self.bus.publish("trigger:events", envelope.model_dump())

    def _send_email(self, subject: str, body: str) -> None:
        """Send a plain-text digest email using the PM3 SMTP settings."""

        message = MIMEMultipart()
        message["From"] = self.settings.SMTP_FROM
        message["To"] = ", ".join(self.settings.SMTP_TO)
        message["Subject"] = subject
        message.attach(MIMEText(body, "plain"))

        with self._smtp_factory(self.settings.SMTP_HOST, int(self.settings.SMTP_PORT)) as smtp:
            if self.settings.SMTP_USER and self.settings.SMTP_PASSWORD:
                smtp.login(self.settings.SMTP_USER, self.settings.SMTP_PASSWORD)
            smtp.send_message(message)

    def _days_since(self, value: datetime | None) -> int:
        """Return the number of whole days since `value`."""

        if value is None:
            return 0
        now = datetime.now(timezone.utc)
        return max(0, (now - value).days)

    def _parse_datetime(self, value: Any) -> datetime | None:
        """Convert DB timestamp values into timezone-aware datetimes."""

        if value is None:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        text_value = str(value).strip()
        if not text_value:
            return None
        try:
            parsed = datetime.fromisoformat(text_value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    def _within_market_hours(self, moment: datetime | None = None) -> bool:
        """Return True when the time falls inside US market hours Monday through Friday."""

        from zoneinfo import ZoneInfo

        moment = moment or datetime.now(ZoneInfo("America/New_York"))
        if moment.weekday() >= 5:
            return False
        market_open = moment.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = moment.replace(hour=16, minute=0, second=0, microsecond=0)
        return market_open <= moment <= market_close

    def guarded_poll_price_moves(self) -> list[M1TriggerEvent]:
        """Run the price poll only during market hours."""

        if not self._within_market_hours():
            return []
        return self.poll_price_moves()


__all__ = ["CoverageMonitor", "PriceWatcher", "CoverageRow"]
