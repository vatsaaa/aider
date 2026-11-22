"""Event bus abstraction and Redis Streams-backed implementation.

This module provides the single `Bus` interface that all agents must use to
interact with Redis Streams. It includes a `RedisStreamsBus` concrete class
that can use a real `redis.Redis` client or `fakeredis.FakeRedis` for tests.

No other module should import `redis` directly; use `RedisStreamsBus` instead.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import redis
from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)


@dataclass
class Message:
    """Represents a deserialised message read from a Redis stream."""

    id: str
    stream: str
    data: Dict[str, Any]
    pipeline_run_id: Optional[str]
    ticker: Optional[str]
    trigger_type: Optional[str]
    timestamp: Optional[str]
    payload: Dict[str, Any]
    metadata: Dict[str, Any]


class BusConnectionError(Exception):
    """Raised when the bus cannot reach Redis."""


class Bus:
    """Abstract interface for a message bus."""

    def publish(self, stream: str, payload: Dict[str, Any]) -> str:
        """Publish `payload` to `stream` and return the Redis message id."""

        raise NotImplementedError()

    def consume(self, stream: str, group: str, consumer: str, count: int = 1, block_ms: int = 5000) -> List[Message]:
        """Consume messages from `stream` using consumer group semantics."""

        raise NotImplementedError()

    def ack(self, stream: str, group: str, message_id: str) -> None:
        """Acknowledge processing of `message_id` in `stream`/`group`."""

        raise NotImplementedError()

    def publish_dlq(self, reason: str, original_stream: str, original_payload: Dict[str, Any], run_id: Optional[str]) -> None:
        """Publish a failure to the DLQ and persist an entry to the DB."""

        raise NotImplementedError()

    def get_stream_length(self, stream: str) -> int:
        """Return the length of `stream` (XLEN)."""

        raise NotImplementedError()

    def flush_stream(self, stream: str) -> None:
        """Delete `stream`. Only allowed in development environment."""

        raise NotImplementedError()

    def get_cache(self, key: str) -> Any:
        """Return the cached value for `key`, or `None` when missing."""

        raise NotImplementedError()

    def set_cache(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        """Store `value` under `key` with an optional TTL."""

        raise NotImplementedError()


class RedisStreamsBus(Bus):
    """Redis Streams-backed Bus implementation.

    Args:
        redis_client: A redis.Redis-like client (real redis or fakeredis).
        db_url: Optional SQLAlchemy database URL; if provided DLQ entries are
            persisted to the `dlq_entries` table.
    """

    def __init__(self, redis_client: redis.Redis, db_url: Optional[str] = None) -> None:
        self._client = redis_client
        self._db_url = db_url or self._settings().AIDER_DATABASE_URL
        self._engine = create_engine(self._db_url) if self._db_url else None

    @staticmethod
    def _settings():
        """Import settings lazily so module import does not require env vars."""

        from core.config import settings

        return settings

    def publish(self, stream: str, payload: Dict[str, Any]) -> str:
        """Serialize `payload` to JSON and XADD to `stream`."""

        try:
            msg_id = self._client.xadd(stream, {"data": json.dumps(payload)})
            return msg_id.decode() if isinstance(msg_id, (bytes, bytearray)) else str(msg_id)
        except redis.exceptions.ConnectionError as exc:
            raise BusConnectionError("Redis unreachable") from exc

    def send(self, stream: str, message: Dict[str, Any]) -> str:
        """Backward-compatible alias for `publish`."""

        return self.publish(stream, message)

    def _ensure_group(self, stream: str, group: str) -> None:
        """Create a consumer group for `stream` if it does not exist."""

        try:
            self._client.xgroup_create(stream, group, id="0", mkstream=True)
        except redis.exceptions.ResponseError as exc:
            if "BUSYGROUP" in str(exc):
                return
            raise

    def consume(self, stream: str, group: str, consumer: str, count: int = 1, block_ms: int = 5000) -> List[Message]:
        """Read messages from `stream` using XREADGROUP and decode them."""

        try:
            self._ensure_group(stream, group)
            entries = self._client.xreadgroup(group, consumer, {stream: ">"}, count=count, block=block_ms)
        except redis.exceptions.ConnectionError as exc:
            raise BusConnectionError("Redis unreachable") from exc

        messages: List[Message] = []
        for stream_name, items in entries:
            for item_id, fields in items:
                raw = fields.get(b"data") if isinstance(fields, dict) else None
                if raw is None and isinstance(fields, dict):
                    raw = fields.get("data")
                try:
                    decoded = raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
                    payload = json.loads(decoded)
                except Exception:
                    logger.exception("Failed to deserialize message, sending to DLQ")
                    try:
                        self.publish_dlq("deserialisation_failure", stream, {"raw": raw.decode() if isinstance(raw, (bytes, bytearray)) else raw}, None)
                    except Exception:
                        logger.exception("Failed to publish deserialisation failure to DLQ")
                    continue

                messages.append(
                    Message(
                        id=item_id.decode() if isinstance(item_id, (bytes, bytearray)) else str(item_id),
                        stream=stream_name.decode() if isinstance(stream_name, (bytes, bytearray)) else str(stream_name),
                        data=payload,
                        pipeline_run_id=payload.get("pipeline_run_id"),
                        ticker=payload.get("ticker"),
                        trigger_type=payload.get("trigger_type"),
                        timestamp=payload.get("timestamp"),
                        payload=payload.get("payload", {}),
                        metadata=payload.get("metadata", {}),
                    )
                )

        return messages

    def read(self, stream: str, count: int = 1) -> List[Dict[str, Any]]:
        """Backward-compatible alias that returns raw envelope dictionaries."""

        messages = self.consume(stream, group="compat-group", consumer="compat-consumer", count=count)
        return [{"id": message.id, "message": message.data} for message in messages]

    def ack(self, stream: str, group: str, message_id: str) -> None:
        """Acknowledge `message_id` in `stream` for `group` (XACK)."""

        try:
            self._client.xack(stream, group, message_id)
        except redis.exceptions.ConnectionError as exc:
            raise BusConnectionError("Redis unreachable") from exc

    def publish_dlq(self, reason: str, original_stream: str, original_payload: Dict[str, Any], run_id: Optional[str]) -> None:
        """Publish a DLQ entry to `dlq:failed` and persist it to PostgreSQL."""

        payload = {
            "reason": reason,
            "original_stream": original_stream,
            "original_payload": original_payload,
            "run_id": run_id,
        }

        try:
            self._client.xadd("dlq:failed", {"data": json.dumps(payload)})
        except redis.exceptions.ConnectionError as exc:
            raise BusConnectionError("Redis unreachable") from exc

        if self._engine is None:
            return

        try:
            with self._engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO dlq_entries (run_id, stream, message_id, reason, payload, created_at) "
                        "VALUES (:run_id, :stream, :message_id, :reason, :payload, CURRENT_TIMESTAMP)"
                    ),
                    {
                        "run_id": run_id,
                        "stream": original_stream,
                        "message_id": None,
                        "reason": reason,
                        "payload": json.dumps(original_payload),
                    },
                )
        except Exception:
            logger.exception("Failed to persist DLQ entry to database")

    def get_stream_length(self, stream: str) -> int:
        """Return XLEN for `stream`."""

        try:
            return int(self._client.xlen(stream))
        except redis.exceptions.ConnectionError as exc:
            raise BusConnectionError("Redis unreachable") from exc

    def flush_stream(self, stream: str) -> None:
        """Delete the Redis stream. Only allowed in development environment."""

        if self._settings().ENV != "development":
            raise RuntimeError("flush_stream is only allowed in development environment")
        try:
            self._client.delete(stream)
        except redis.exceptions.ConnectionError as exc:
            raise BusConnectionError("Redis unreachable") from exc

    def get_cache(self, key: str) -> Any:
        """Read a cached value from Redis and return the raw payload."""

        try:
            cached = self._client.get(key)
        except redis.exceptions.ConnectionError as exc:
            raise BusConnectionError("Redis unreachable") from exc

        if cached is None:
            return None

        if isinstance(cached, (bytes, bytearray)):
            try:
                return cached.decode()
            except Exception:
                return cached
        return cached

    def set_cache(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        """Store a cache entry in Redis with an optional expiry."""

        try:
            if ttl_seconds is None:
                self._client.set(key, value)
            else:
                self._client.set(key, value, ex=ttl_seconds)
        except redis.exceptions.ConnectionError as exc:
            raise BusConnectionError("Redis unreachable") from exc


class InMemoryBus(Bus):
    """A simple in-memory Bus used for unit tests and local development."""

    def __init__(self) -> None:
        from collections import defaultdict, deque
        from threading import Lock

        self._streams: Dict[str, Any] = defaultdict(deque)
        self._locks: Dict[str, Any] = defaultdict(Lock)
        self._counters: Dict[str, int] = defaultdict(int)
        self._cache: Dict[str, Any] = {}

    def publish(self, stream: str, payload: Dict[str, Any]) -> str:
        with self._locks[stream]:
            self._counters[stream] += 1
            msg_id = str(self._counters[stream])
            self._streams[stream].append({"id": msg_id, "data": json.dumps(payload)})
            return msg_id

    def send(self, stream: str, message: Dict[str, Any]) -> str:
        """Backward-compatible alias for `publish`."""

        return self.publish(stream, message)

    def consume(self, stream: str, group: str, consumer: str, count: int = 1, block_ms: int = 5000) -> List[Message]:
        with self._locks[stream]:
            out: List[Message] = []
            for _ in range(min(count, len(self._streams[stream]))):
                item = self._streams[stream].popleft()
                payload = json.loads(item["data"])
                out.append(
                    Message(
                        id=item["id"],
                        stream=stream,
                        data=payload,
                        pipeline_run_id=payload.get("pipeline_run_id"),
                        ticker=payload.get("ticker"),
                        trigger_type=payload.get("trigger_type"),
                        timestamp=payload.get("timestamp"),
                        payload=payload.get("payload", {}),
                        metadata=payload.get("metadata", {}),
                    )
                )
            return out

    def read(self, stream: str, count: int = 1) -> List[Dict[str, Any]]:
        """Backward-compatible alias returning the legacy envelope format."""

        with self._locks[stream]:
            out: List[Dict[str, Any]] = []
            for _ in range(min(count, len(self._streams[stream]))):
                item = self._streams[stream].popleft()
                out.append({"id": item["id"], "message": json.loads(item["data"])})
            return out

    def ack(self, stream: str, group: str, message_id: str) -> None:
        return None

    def publish_dlq(self, reason: str, original_stream: str, original_payload: Dict[str, Any], run_id: Optional[str]) -> None:
        self.publish("dlq:failed", {"reason": reason, "original_stream": original_stream, "original_payload": original_payload, "run_id": run_id})

    def get_stream_length(self, stream: str) -> int:
        return len(self._streams[stream])

    def flush_stream(self, stream: str) -> None:
        if RedisStreamsBus._settings().ENV != "development":
            raise RuntimeError("flush_stream is only allowed in development environment")
        self._streams.pop(stream, None)
        self._counters.pop(stream, None)

    def get_cache(self, key: str) -> Any:
        entry = self._cache.get(key)
        if entry is None:
            return None

        expires_at = entry.get("expires_at")
        if expires_at is not None and expires_at <= datetime.now(timezone.utc).timestamp():
            self._cache.pop(key, None)
            return None

        return entry.get("value")

    def set_cache(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        expires_at = None
        if ttl_seconds is not None:
            expires_at = datetime.now(timezone.utc).timestamp() + ttl_seconds
        self._cache[key] = {"value": value, "expires_at": expires_at}