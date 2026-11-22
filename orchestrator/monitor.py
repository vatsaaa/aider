"""Orchestrator monitor: manage retries, backoff, and run failures.

This process polls the Redis DLQ stream `dlq:failed`, groups failures by
`run_id`, applies an exponential backoff schedule, republishes original
payloads when their retry window has elapsed, and marks runs FAILED after
`MAX_RETRY_ATTEMPTS`.

Run with: `python -m orchestrator.monitor`
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import redis
from sqlalchemy import create_engine, inspect, text

from core.config import settings
from core.logger import get_logger
from core.bus import RedisStreamsBus


@dataclass
class DLQEntry:
    id: str
    run_id: Optional[str]
    original_stream: Optional[str]
    original_payload: Dict[str, Any]
    ts_ms: int


class OrchestratorMonitor:
    """Poll Redis DLQ, enforce backoff, republish, and mark failed runs."""

    def __init__(
        self,
        *,
        poll_interval: int = 30,
        base_delay_seconds: int = 60,
        max_attempts: int = 3,
        redis_client: Any | None = None,
        db_engine: Any | None = None,
    ) -> None:
        self.logger = get_logger(agent="orchestrator")
        self.poll_interval = poll_interval
        self.base_delay_seconds = base_delay_seconds
        self.max_attempts = max_attempts

        # Allow injection for tests; fall back to configured endpoints
        self.redis = redis_client or redis.Redis.from_url(settings.REDIS_URL)
        self.db_engine = db_engine or (create_engine(settings.AIDER_DATABASE_URL) if getattr(settings, "AIDER_DATABASE_URL", None) else None)
        self.bus = RedisStreamsBus(self.redis, db_url=getattr(settings, "AIDER_DATABASE_URL", None))

    def run(self) -> None:
        self.logger.info("orchestrator_started", poll_interval=self.poll_interval)
        try:
            while True:
                try:
                    self._poll_once()
                except Exception as exc:
                    self.logger.error("orchestrator_poll_error", error=str(exc))
                time.sleep(self.poll_interval)
        except KeyboardInterrupt:
            self.logger.info("orchestrator_stopped")

    def _poll_once(self) -> None:
        entries = self._read_dlq_stream()
        grouped = self._group_by_run(entries)

        now_ms = int(time.time() * 1000)
        for run_id, dlq_entries in grouped.items():
            failures = len(dlq_entries)
            last_ts = max(e.ts_ms for e in dlq_entries)

            # If we've exceeded max attempts, mark failed and alert humans
            if failures >= self.max_attempts:
                self._mark_run_failed(run_id, dlq_entries)
                continue

            # compute exponential backoff next retry timestamp in ms
            delay = self.base_delay_seconds * (2 ** (failures - 1))
            next_retry_ms = last_ts + int(delay * 1000)
            if now_ms >= next_retry_ms:
                self.logger.info("orchestrator_requeue_run", run_id=run_id, failures=failures)
                # republish original payloads and remove DLQ entries
                for entry in dlq_entries:
                    if entry.original_stream and entry.original_payload:
                        try:
                            self.bus.publish(entry.original_stream, entry.original_payload)
                            # delete the specific DLQ stream entry
                            try:
                                self.redis.xdel("dlq:failed", entry.id)
                            except Exception:
                                pass
                            # record retry in DB if possible
                            try:
                                self._record_dlq_retry(entry.id)
                            except Exception:
                                pass
                        except Exception as exc:
                            self.logger.error("orchestrator_republish_failed", run_id=run_id, entry_id=entry.id, error=str(exc))

    def _read_dlq_stream(self) -> List[DLQEntry]:
        """Read all entries from the `dlq:failed` stream and return decoded list."""

        out: List[DLQEntry] = []
        try:
            raw = self.redis.xrange("dlq:failed", min='-', max='+') or []
        except Exception:
            self.logger.error("orchestrator_dlq_read_failed")
            return out

        for item_id, fields in raw:
            try:
                data_raw = fields.get(b"data") if isinstance(fields, dict) else None
                if data_raw is None:
                    continue
                decoded = data_raw.decode() if isinstance(data_raw, (bytes, bytearray)) else data_raw
                payload = json.loads(decoded)
            except Exception:
                continue

            run_id = payload.get("run_id") or payload.get("runId") or payload.get("run") or payload.get("run_id")
            original_stream = payload.get("original_stream") or payload.get("stream")
            original_payload = payload.get("original_payload") or payload.get("original_payload") or payload.get("original") or {}

            # Redis stream id is like '1597763333444-0' (ms-seq)
            try:
                raw_id = item_id.decode() if isinstance(item_id, (bytes, bytearray)) else str(item_id)
                ts_ms = int(raw_id.split("-")[0])
            except Exception:
                ts_ms = int(time.time() * 1000)

            out.append(DLQEntry(id=item_id.decode() if isinstance(item_id, (bytes, bytearray)) else str(item_id), run_id=run_id, original_stream=original_stream, original_payload=original_payload, ts_ms=ts_ms))

        return out

    def _group_by_run(self, entries: List[DLQEntry]) -> Dict[str, List[DLQEntry]]:
        grouped: Dict[str, List[DLQEntry]] = {}
        for e in entries:
            key = e.run_id or f"unknown:{e.id}"
            grouped.setdefault(key, []).append(e)
        return grouped

    def _mark_run_failed(self, run_id: Optional[str], dlq_entries: List[DLQEntry]) -> None:
        """Mark a pipeline run as failed (if DB table exists) and publish an alert."""

        self.logger.warning("orchestrator_marking_failed", run_id=run_id, failures=len(dlq_entries))

        # Update pipeline_runs.status when table exists
        if self.db_engine is not None:
            try:
                inspector = inspect(self.db_engine)
                if inspector.has_table("pipeline_runs"):
                    with self.db_engine.begin() as conn:
                        try:
                            conn.execute(text("UPDATE pipeline_runs SET status = :status, completed_at = :completed_at WHERE run_id = :run_id"), {"status": "failed", "completed_at": datetime.now(timezone.utc), "run_id": run_id})
                        except Exception:
                            # best-effort — ignore schema mismatches
                            pass
            except Exception:
                pass

        # Publish a human alert to Redis stream `alerts:human`
        alert = {
            "run_id": run_id,
            "failed_at": datetime.now(timezone.utc).isoformat(),
            "failures": len(dlq_entries),
            "reason": "max_retry_exceeded",
            "dlq_entries": [e.id for e in dlq_entries],
        }
        try:
            self.bus.publish("alerts:human", alert)
        except Exception:
            self.logger.error("orchestrator_alert_publish_failed", run_id=run_id)
        # send external alerts (Slack/email) when configured
        try:
            self._send_slack(alert)
        except Exception:
            self.logger.exception("slack_alert_failed", run_id=run_id)
        try:
            self._send_email(alert)
        except Exception:
            self.logger.exception("email_alert_failed", run_id=run_id)

    def _record_dlq_retry(self, dlq_entry_id: str) -> None:
        """Insert a retry record into `dlq_retries` when the table exists.

        This is best-effort: if the table or columns are missing we silently
        continue.
        """
        if self.db_engine is None:
            return
        try:
            inspector = inspect(self.db_engine)
            if not inspector.has_table("dlq_retries"):
                return
            with self.db_engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO dlq_retries (dlq_entry_id, retried_at) VALUES (:dlq_entry_id, :retried_at)"
                    ),
                    {"dlq_entry_id": dlq_entry_id, "retried_at": datetime.now(timezone.utc)},
                )
        except Exception:
            # best-effort
            return

    def _send_slack(self, alert: Dict[str, Any]) -> None:
        """Send a Slack message to configured webhook when available."""
        url = getattr(settings, "SLACK_WEBHOOK_URL", None)
        if not url:
            return
        try:
            import requests

            text = f"[Orchestrator] Run {alert.get('run_id')} failed after {alert.get('failures')} attempts: {alert.get('reason')}"
            max_retries = getattr(settings, "ALERT_MAX_RETRIES", 3)
            base = getattr(settings, "ALERT_RETRY_BASE_SECONDS", 5)
            for attempt in range(1, max_retries + 1):
                try:
                    resp = requests.post(url, json={"text": text}, timeout=5)
                    resp.raise_for_status()
                    return
                except Exception as exc:
                    self.logger.warning("slack alert attempt %s/%s failed: %s", attempt, max_retries, exc)
                    if attempt == max_retries:
                        self.logger.exception("slack alert failed after %s attempts", max_retries)
                        # record failure to DB (best-effort)
                        try:
                            self._record_alert_failure("slack", {"text": text}, str(exc))
                        except Exception:
                            self.logger.exception("failed to record slack alert failure to DB")
                        return
                    sleep_seconds = base * (2 ** (attempt - 1))
                    time.sleep(sleep_seconds)
        except Exception:
            # any import/other problem should not crash monitor
            self.logger.exception("unexpected error while sending slack alert")

    def _send_email(self, alert: Dict[str, Any]) -> None:
        """Send a simple notification email using configured SMTP settings."""
        # Only send if SMTP_TO configured
        if not getattr(settings, "SMTP_TO", None):
            return
        try:
            import smtplib
            from email.mime.text import MIMEText

            body = (
                f"Orchestrator alert:\n\nRun: {alert.get('run_id')}\nFailures: {alert.get('failures')}\nReason: {alert.get('reason')}\nTime: {alert.get('failed_at')}\n"
            )
            msg = MIMEText(body)
            msg["From"] = settings.SMTP_FROM
            msg["To"] = ", ".join(settings.SMTP_TO or [])
            msg["Subject"] = f"Orchestrator alert: run {alert.get('run_id')} failed"

            smtp_host = settings.SMTP_HOST
            smtp_port = int(settings.SMTP_PORT or 1025)
            max_retries = getattr(settings, "ALERT_MAX_RETRIES", 3)
            base = getattr(settings, "ALERT_RETRY_BASE_SECONDS", 5)
            for attempt in range(1, max_retries + 1):
                try:
                    with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as smtp:
                        if getattr(settings, "SMTP_USER", None) and getattr(settings, "SMTP_PASSWORD", None):
                            smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                        smtp.sendmail(settings.SMTP_FROM, settings.SMTP_TO or [], msg.as_string())
                    return
                except Exception as exc:
                    self.logger.warning("email alert attempt %s/%s failed: %s", attempt, max_retries, exc)
                    if attempt == max_retries:
                        self.logger.exception("email alert failed after %s attempts", max_retries)
                        try:
                            self._record_alert_failure("email", {"subject": msg["Subject"], "body": body}, str(exc))
                        except Exception:
                            self.logger.exception("failed to record email alert failure to DB")
                        return
                    sleep_seconds = base * (2 ** (attempt - 1))
                    time.sleep(sleep_seconds)
        except Exception:
            self.logger.exception("unexpected error while sending email alert")

    def _record_alert_failure(self, channel: str, payload: dict, error_message: str) -> None:
        """Record alert send failures into `alerts_failures` table (best-effort)."""
        if self.db_engine is None:
            return
        try:
            inspector = inspect(self.db_engine)
            if not inspector.has_table("alerts_failures"):
                return
            with self.db_engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO alerts_failures (channel, payload, error_message, failed_at) VALUES (:channel, :payload, :err, :failed_at)"
                    ),
                    {"channel": channel, "payload": json.dumps(payload), "err": error_message, "failed_at": datetime.now(timezone.utc)},
                )
        except Exception:
            # best-effort only
            self.logger.exception("failed to persist alert failure to DB")


def build_parser() -> Any:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m orchestrator.monitor")
    parser.add_argument("--poll-interval", type=int, default=30, help="Seconds between DLQ polls")
    parser.add_argument("--base-delay", type=int, default=60, help="Base delay in seconds for exponential backoff")
    parser.add_argument("--max-attempts", type=int, default=3, help="Max retry attempts before failing run")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    monitor = OrchestratorMonitor(poll_interval=args.poll_interval, base_delay_seconds=args.base_delay, max_attempts=args.max_attempts)
    monitor.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
