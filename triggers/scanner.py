"""Trigger scanner orchestrator for the runnable trigger process.

This module wires the existing watcher classes onto APScheduler so the trigger
pipeline can run as a single long-lived process. It also exposes a manual
trigger path for ad-hoc runs and tests.
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import redis
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import create_engine

from core.bus import RedisStreamsBus
from core.config import Settings, settings
from core.schemas import M1TriggerEvent, MessageEnvelope
from db.pipeline_runs import ensure_pipeline_run
from triggers.edgar_watcher import EdgarWatcher
from triggers.earnings_watcher import EarningsWatcher
from triggers.fred_watcher import FredWatcher


TRIGGER_STREAM = "trigger:events"


@dataclass
class TriggerJobs:
    """Bundle the scheduled watcher jobs for inspection in tests."""

    edgar: Any
    fred: Any
    earnings: Any


class TriggerScanner:
    """Coordinate trigger watchers and manual trigger publication."""

    def __init__(
        self,
        bus: RedisStreamsBus,
        db: Any,
        settings: Settings,
        scheduler: BackgroundScheduler | None = None,
    ) -> None:
        self.bus = bus
        self.db = db
        self.settings = settings
        self.scheduler = scheduler or BackgroundScheduler()

        self.edgar_watcher = EdgarWatcher(bus=bus, db=db, settings=settings)
        self.fred_watcher = FredWatcher(bus=bus, db=db, settings=settings)
        self.earnings_watcher = EarningsWatcher(bus=bus, db=db, settings=settings)
        self.jobs = self._register_jobs()

    def _register_jobs(self) -> TriggerJobs:
        """Register the watcher polling jobs on the scheduler."""

        edgar_job = self.scheduler.add_job(
            self.edgar_watcher.poll,
            trigger=IntervalTrigger(minutes=15),
            id="edgar_watcher_poll",
            name="EdgarWatcher.poll",
            replace_existing=True,
            max_instances=1,
        )
        fred_job = self.scheduler.add_job(
            self.fred_watcher.poll,
            trigger=IntervalTrigger(minutes=60),
            id="fred_watcher_poll",
            name="FredWatcher.poll",
            replace_existing=True,
            max_instances=1,
        )
        earnings_job = self.scheduler.add_job(
            self.earnings_watcher.poll,
            trigger=IntervalTrigger(minutes=60),
            id="earnings_watcher_poll",
            name="EarningsWatcher.poll",
            replace_existing=True,
            max_instances=1,
        )
        return TriggerJobs(edgar=edgar_job, fred=fred_job, earnings=earnings_job)

    def publish_manual_trigger(self, ticker: str, trigger_type: str = "manual") -> M1TriggerEvent:
        """Publish a manual M1 trigger onto the trigger stream."""

        event = M1TriggerEvent(
            ticker=ticker.upper(),
            trigger_type=trigger_type,
            pipeline_run_id=str(uuid4()),
        )
        envelope = MessageEnvelope(
            message_id=str(uuid4()),
            pipeline_run_id=event.pipeline_run_id,
            trigger_type=event.trigger_type,
            ticker=event.ticker,
            timestamp=datetime.now(timezone.utc).isoformat(),
            payload=event.model_dump(),
            metadata={
                "source": "scanner",
                "manual": True,
            },
        )
        ensure_pipeline_run(
            self.db,
            run_id=event.pipeline_run_id,
            ticker=event.ticker,
            trigger_type=event.trigger_type,
            status="started",
        )
        self.bus.publish(TRIGGER_STREAM, envelope.model_dump())
        return event

    def run(self) -> None:
        """Start the scheduler and block until interrupted."""

        if not self.scheduler.running:
            self.scheduler.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            return
        finally:
            if self.scheduler.running:
                self.scheduler.shutdown(wait=False)


def _build_scanner() -> TriggerScanner:
    """Create a scanner wired to the configured Redis and PostgreSQL endpoints."""

    redis_client = redis.Redis.from_url(settings.REDIS_URL)
    db_engine = create_engine(settings.DATABASE_URL)
    bus = RedisStreamsBus(redis_client, db_url=settings.DATABASE_URL)
    return TriggerScanner(bus=bus, db=db_engine, settings=settings)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for the scanner process."""

    parser = argparse.ArgumentParser(prog="python -m triggers.scanner")
    parser.add_argument("--manual", action="store_true", help="Publish a single manual trigger and exit")
    parser.add_argument("--ticker", help="Ticker to use for a manual trigger")
    parser.add_argument(
        "--type",
        dest="trigger_type",
        default="manual",
        choices=["8-K", "10-Q", "10-K", "earnings", "fred_release", "manual"],
        help="Trigger type to publish for a manual run",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint used by `python -m triggers.scanner`."""

    parser = build_parser()
    args = parser.parse_args(argv)

    scanner = _build_scanner()
    if args.manual:
        if not args.ticker:
            parser.error("--ticker is required when --manual is set")
        scanner.publish_manual_trigger(args.ticker, args.trigger_type)
        return 0

    scanner.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())