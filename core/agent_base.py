"""Shared base class for all pipeline agents.

The base agent owns the consume → process → publish → ack lifecycle, handles
fatal versus transient failures, and provides structured logging plus LLM
routing helpers for downstream agents.
"""

from __future__ import annotations

import importlib
import json
import time
import traceback
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Protocol, TYPE_CHECKING
from uuid import uuid4

from pydantic import BaseModel
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine

from core.bus import Bus, Message
from core.exceptions import FatalError
from core.logger import configure_logging, get_logger
from core.schemas import MessageEnvelope
from db.repositories import AgentRepository

if TYPE_CHECKING:
    from core.config import Settings


class Database(Protocol):
    """Structural type for the database handle used by agents."""


class BaseAgent(ABC):
    """Base class that implements the standard agent processing loop."""

    stream_in: str | tuple[str, ...]
    stream_out: str
    group_name: str
    agent_name: str

    def __init__(self, bus: Bus, db: Database, settings: "Settings") -> None:
        """Store runtime dependencies and initialize structured logging."""

        configure_logging()
        self.bus = bus
        self.db = db
        self.settings = settings
        self.repository = AgentRepository(db)
        self._logger = get_logger(agent_name=self.agent_name)
        self._current_started_at: float | None = None

    def run(self) -> None:
        """Main blocking loop for consume → process → publish → ack.

        The loop continues to poll the input stream until a `StopIteration`
        signal is raised by the bus (used in tests) or the process is
        interrupted. Fatal errors are sent to the DLQ and acknowledged. All
        other exceptions are logged and left unacked for Redis redelivery.
        """

        consumer_name = self.agent_name
        streams = self._input_streams()
        while True:
            try:
                for stream in streams:
                    messages = self.bus.consume(
                        stream,
                        self.group_name,
                        consumer_name,
                        count=1,
                        block_ms=5000 if len(streams) == 1 else 1000,
                    )
                    if not messages:
                        continue

                    for message in messages:
                        self._current_started_at = time.perf_counter()
                        try:
                            self._ensure_pipeline_run(message)
                            result = self.process(message)
                            if result is not None:
                                self.publish_result(result, message)
                            else:
                                self.log(
                                    "agent_skipped",
                                    level="info",
                                    run_id=message.pipeline_run_id,
                                    ticker=message.ticker,
                                    stream=stream,
                                    duration_ms=self._duration_ms(),
                                    reason="process_returned_none",
                                )
                            self.bus.ack(stream, self.group_name, message.id)
                            if result is not None:
                                self.log_success(message, result, stream=stream)
                            self._record_audit_log(message, result=result)
                        except FatalError as error:
                            self._handle_fatal_error(message, error, stream=stream)
                            self._record_audit_log(message, error=error)
                        except Exception as error:
                            self.log_error(message, error, stream=stream)
                            self._record_audit_log(message, error=error)
                        finally:
                            self._current_started_at = None
            except StopIteration:
                break

    @abstractmethod
    def process(self, message: Message) -> BaseModel:
        """Transform an input message into the next-stage payload."""

    def publish_result(self, result: BaseModel, original: Message) -> None:
        """Wrap a stage result in `MessageEnvelope` and publish it downstream."""

        envelope = MessageEnvelope(
            message_id=str(uuid4()),
            pipeline_run_id=original.pipeline_run_id or "",
            trigger_type=original.trigger_type or original.data.get("trigger_type", "manual"),
            ticker=original.ticker or original.data.get("ticker", ""),
            timestamp=datetime.now(timezone.utc).isoformat(),
            payload=result.model_dump(),
            metadata=dict(original.metadata or {}),
        )
        self.bus.publish(self.stream_out, envelope.model_dump())

    def _input_streams(self) -> tuple[str, ...]:
        """Return the configured input streams as a normalized tuple."""

        if isinstance(self.stream_in, str):
            return (self.stream_in,) if self.stream_in else ()
        return tuple(self.stream_in)

    def _ensure_pipeline_run(self, message: Message) -> None:
        """Insert the parent pipeline run row before downstream tables write children.

        The insert is idempotent and is skipped when the agent has no database
        handle or when the `pipeline_runs` table is not present in the current
        test harness.
        """

        self.repository.ensure_pipeline_run(
            run_id=message.pipeline_run_id or message.data.get("pipeline_run_id"),
            ticker=message.ticker or message.data.get("ticker") or "",
            trigger_type=message.trigger_type or message.data.get("trigger_type") or "manual",
            status="started",
        )

    def call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        response_schema: dict[str, Any] | None = None,
        max_tokens: int = 1000,
    ) -> str | dict[str, Any]:
        """Route an LLM request through the centralized router.

        This method only delegates to the router module; it never calls any
        provider client directly.
        """

        candidate_modules = ("llm.router", "aider.llm.router")
        for module_name in candidate_modules:
            try:
                module = importlib.import_module(module_name)
            except ModuleNotFoundError:
                continue
            router_call = getattr(module, "call_llm", None)
            if callable(router_call):
                return router_call(
                    agent_name=self.agent_name,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    response_schema=response_schema,
                    max_tokens=max_tokens,
                    settings=self.settings,
                )

        raise RuntimeError("LLM router is not available yet")

    def log(self, event: str, level: str = "info", **extra: Any) -> None:
        """Emit a structured JSON log line.

        Every log line includes the agent name, stream, run identifier, and
        ticker so downstream debugging and audit tooling can correlate events.
        """

        payload = {
            "agent_name": self.agent_name,
            "run_id": extra.pop("run_id", None),
            "ticker": extra.pop("ticker", None),
            "stream": extra.pop("stream", None),
            **extra,
        }
        logger_method = getattr(self._logger, level.lower(), self._logger.info)
        logger_method(event, **payload)

    def log_success(self, message: Message, result: BaseModel, stream: str | None = None) -> None:
        """Log successful processing with a duration in milliseconds."""

        duration_ms = self._duration_ms()
        self.log(
            "agent_success",
            level="info",
            run_id=message.pipeline_run_id,
            ticker=message.ticker,
            stream=stream or self._input_streams()[0],
            duration_ms=duration_ms,
            result_type=result.__class__.__name__,
        )

    def log_error(self, message: Message, error: Exception, stream: str | None = None) -> None:
        """Log a failure with the full traceback attached."""

        self.log(
            "agent_error",
            level="error",
            run_id=message.pipeline_run_id,
            ticker=message.ticker,
            stream=stream or self._input_streams()[0],
            duration_ms=self._duration_ms(),
            error_type=error.__class__.__name__,
            error_message=str(error),
            traceback=traceback.format_exc(),
        )

    def _record_audit_log(
        self,
        message: Message,
        *,
        result: BaseModel | None = None,
        error: Exception | None = None,
    ) -> None:
        """Persist a durable audit row for the current stage transition.

        Audit logging is best-effort: failures are swallowed so observability
        never blocks the main agent flow.
        """

        if self.db is None:
            return

        run_id = message.pipeline_run_id or message.data.get("pipeline_run_id")
        if not run_id:
            return

        try:
            inspector = inspect(self.db)
            if not inspector.has_table("audit_log"):
                return
            columns = {column["name"] for column in inspector.get_columns("audit_log")}
        except Exception:
            return

        verdict, issues = self._audit_row_values(result=result, error=error)
        values: dict[str, Any] = {"run_id": run_id, "stage": self.agent_name}
        insert_columns = ["run_id", "stage"]

        if "verdict" in columns:
            values["verdict"] = verdict
            insert_columns.append("verdict")
        if "issues" in columns:
            values["issues"] = json.dumps(issues)
            insert_columns.append("issues")
        if "created_at" in columns:
            values["created_at"] = datetime.now(timezone.utc).isoformat()
            insert_columns.append("created_at")

        statement = text(
            f"INSERT INTO audit_log ({', '.join(insert_columns)}) "
            f"VALUES ({', '.join(f':{column}' for column in insert_columns)})"
        )

        try:
            if isinstance(self.db, Engine):
                with self.db.begin() as connection:
                    connection.execute(statement, values)
            else:
                assert isinstance(self.db, Connection)
                self.db.execute(statement, values)
        except Exception:
            self.log(
                "audit_log_write_failed",
                level="error",
                run_id=run_id,
                ticker=message.ticker,
                stream=self.stream_in,
                error_type="AuditLogWriteFailed",
            )

    def _audit_row_values(
        self,
        *,
        result: BaseModel | None = None,
        error: Exception | None = None,
    ) -> tuple[str, list[str]]:
        """Derive a concise audit verdict and issue list from the outcome."""

        if error is not None:
            if isinstance(error, FatalError):
                return "FATAL", [error.reason]
            return "ERROR", [f"{error.__class__.__name__}: {error}"]

        if result is None:
            return "SKIPPED", ["process_returned_none"]

        payload = result.model_dump() if hasattr(result, "model_dump") else {}
        verdict = payload.get("verdict")
        if isinstance(verdict, str) and verdict:
            return verdict, self._audit_issues_from_payload(payload)

        status = payload.get("status")
        if isinstance(status, str) and status:
            return status.upper(), self._audit_issues_from_payload(payload)

        if self.agent_name == "pm2_compliance":
            return "APPROVED", self._audit_issues_from_payload(payload)

        if self.agent_name == "pm3_publisher":
            return "PUBLISHED", self._audit_issues_from_payload(payload)

        return "SUCCESS", self._audit_issues_from_payload(payload)

    def _audit_issues_from_payload(self, payload: dict[str, Any]) -> list[str]:
        """Extract a normalized issue list from a result payload."""

        raw_issues = payload.get("issues")
        if isinstance(raw_issues, list):
            return [str(issue) for issue in raw_issues]
        if raw_issues is None:
            return []
        return [str(raw_issues)]

    def _handle_fatal_error(self, message: Message, error: FatalError, stream: str | None = None) -> None:
        """Route fatal failures to the DLQ and acknowledge the message."""

        try:
            self.bus.publish_dlq(
                error.reason,
                stream or self._input_streams()[0],
                message.data,
                error.run_id or message.pipeline_run_id,
            )
        except Exception as dlq_error:
            self.log(
                "dlq_publish_failed",
                level="error",
                run_id=message.pipeline_run_id,
                ticker=message.ticker,
                stream=stream or self._input_streams()[0],
                error_type=dlq_error.__class__.__name__,
                error_message=str(dlq_error),
                traceback=traceback.format_exc(),
            )
        finally:
            self.bus.ack(stream or self._input_streams()[0], self.group_name, message.id)

        self.log_error(message, error)

    def _duration_ms(self) -> int | None:
        """Return the current message processing duration in milliseconds."""

        if self._current_started_at is None:
            return None
        return int((time.perf_counter() - self._current_started_at) * 1000)


__all__ = ["BaseAgent", "Database"]
