"""Arbiter agent: aggregate critic verdicts and route PASS/FATAL decisions.

The arbiter listens on the `critic:verdict:input` stream, collects the three
critic verdicts for a given `pipeline_run_id` in a Redis hash keyed at
`arbiter:state:{pipeline_run_id}`, and only makes a decision once all three
critics have reported.

If any critic reports `FATAL` the arbiter rejects the draft and publishes a
combined `M9CritiqueVerdict` to `critic:revision:input` (unless the max
revision iterations have been exceeded, in which case the message is routed
to the DLQ). If no `FATAL` verdicts are present the arbiter publishes a
`PASS` verdict to `critique:verdict` and includes any `WARN` issues as
advisories.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import time
from typing import Any, Dict, List, Optional
from uuid import uuid4
from datetime import datetime, timezone

from pydantic import BaseModel

from core.agent_base import BaseAgent
from core.bus import Bus, Message
from core.schemas import M9CritiqueVerdict, MessageEnvelope


class Arbiter(BaseAgent):
    """Aggregate critic verdicts and publish a final decision.

    The arbiter supports both a real Redis-backed `RedisStreamsBus` (accessed
    via `self.bus._client`) and the test `InMemoryBus`. For tests the arbiter
    keeps an internal in-memory state with TTL semantics so assertions about
    expiry can be performed.
    """

    stream_in = "critic:verdict:input"
    stream_out = "critique:verdict"
    group_name = "arbiter-group"
    agent_name = "arbiter"

    STATE_KEY_FMT = "arbiter:state:{run_id}"
    STATE_TTL = 3600

    def __init__(self, bus: Bus, db: Any, settings: Any) -> None:
        super().__init__(bus=bus, db=db, settings=settings)
        # local in-memory fallback state used when the Bus does not expose
        # a raw redis client (tests use InMemoryBus)
        self._local_state: Dict[str, Dict[str, Any]] = {}
        self._local_expirations: Dict[str, float] = {}

    def process(self, message: Message) -> BaseModel:
        """Handle a single critic verdict message.

        This method stores the verdict in the per-run state and, if all three
        critics have reported, performs the final pass/fatal decision and
        publishes the appropriate downstream message(s).
        """

        payload = message.payload or message.data.get("payload", {})
        pipeline_run_id = message.pipeline_run_id or payload.get("pipeline_run_id")
        critic = payload.get("critic")
        if not pipeline_run_id or not critic:
            # malformed message — route to DLQ
            self.bus.publish_dlq("arbiter_malformed_input", message.stream, message.data, pipeline_run_id)
            return M9CritiqueVerdict.model_construct(
                {
                    "critic": "arbiter",
                    "verdict": "FATAL",
                    "issues": ["malformed_input"],
                    "iteration": payload.get("iteration", 1),
                    "pipeline_run_id": pipeline_run_id or "",
                }
            )

        # store the incoming verdict
        self._store_verdict(pipeline_run_id, critic, payload)
        # ensure TTL is set
        self._set_state_ttl(pipeline_run_id, self.STATE_TTL)

        # check if we have all three critics
        current = self._get_state(pipeline_run_id)
        if len(current) < 3:
            # not ready yet
            return M9CritiqueVerdict.model_construct(
                {
                    "critic": "arbiter",
                    "verdict": "WARN",
                    "issues": [],
                    "iteration": payload.get("iteration", 1),
                    "pipeline_run_id": pipeline_run_id,
                }
            )

        # aggregate verdicts
        verdicts = list(current.values())
        has_fatal = any(v.get("verdict") == "FATAL" for v in verdicts)
        warns = [issue for v in verdicts for issue in v.get("issues", []) if v.get("verdict") == "WARN"]
        fatals = [issue for v in verdicts for issue in v.get("issues", []) if v.get("verdict") == "FATAL"]
        iteration = max(v.get("iteration", 1) for v in verdicts)

        if has_fatal:
            # if max iterations reached -> DLQ
            if iteration >= getattr(self.settings, "MAX_REVISION_ITERATIONS", 3):
                # publish to DLQ and do not send revision
                combined = {"issues": warns + fatals, "verdicts": verdicts}
                self.bus.publish_dlq("max_revisions_exceeded", self.stream_in, combined, pipeline_run_id)
                return M9CritiqueVerdict.model_construct(
                    {
                        "critic": "arbiter",
                        "verdict": "FATAL",
                        "issues": warns + fatals,
                        "iteration": iteration,
                        "pipeline_run_id": pipeline_run_id,
                    }
                )

            # publish revision request to PM1 via critic:revision:input
            revision_payload = {
                "critic": "arbiter",
                "verdict": "FATAL",
                "issues": warns + fatals,
                "iteration": iteration,
                "pipeline_run_id": pipeline_run_id,
            }
            envelope = self._make_envelope(original=message, payload=revision_payload)
            self.bus.publish("critic:revision:input", envelope)

            return M9CritiqueVerdict.model_construct(revision_payload)

        # No fatals -> PASS (WARNs included as advisory issues)
        pass_payload = {
            "critic": "arbiter",
            "verdict": "PASS",
            "issues": warns,
            "iteration": iteration,
            "pipeline_run_id": pipeline_run_id,
        }
        envelope = self._make_envelope(original=message, payload=pass_payload)
        self.bus.publish("critique:verdict", envelope)

        return M9CritiqueVerdict.model_construct(pass_payload)

    def publish_result(self, result: BaseModel, original: Message) -> None:
        """Suppress the base publish step because Arbiter publishes directly in `process`."""

        return None

    # -- Redis / local state helpers
    def _redis_client(self):
        """Return the raw redis client if available on the bus, else None."""

        return getattr(self.bus, "_client", None)

    def _state_key(self, run_id: str) -> str:
        return self.STATE_KEY_FMT.format(run_id=run_id)

    def _store_verdict(self, run_id: str, critic: str, verdict: Dict[str, Any]) -> None:
        client = self._redis_client()
        if client is not None:
            # store JSON string under the critic field
            client.hset(self._state_key(run_id), critic, json.dumps(verdict))
            return

        # fallback: in-memory
        self._local_state.setdefault(run_id, {})[critic] = verdict

    def _get_state(self, run_id: str) -> Dict[str, Any]:
        client = self._redis_client()
        if client is not None:
            raw = client.hgetall(self._state_key(run_id)) or {}
            parsed: Dict[str, Any] = {}
            for k, v in raw.items():
                key = k.decode() if isinstance(k, (bytes, bytearray)) else str(k)
                val = v.decode() if isinstance(v, (bytes, bytearray)) else v
                try:
                    parsed[key] = json.loads(val)
                except Exception:
                    parsed[key] = {}
            return parsed

        return self._local_state.get(run_id, {})

    def _set_state_ttl(self, run_id: str, seconds: int) -> None:
        client = self._redis_client()
        key = self._state_key(run_id)
        if client is not None:
            client.expire(key, seconds)
            return

        # local fallback: store expiry timestamp
        self._local_expirations[run_id] = time.time() + seconds

    def get_state_ttl(self, run_id: str) -> Optional[int]:
        """Return the remaining TTL (seconds) for the run state, or None.

        This helper is provided for tests to assert the arbiter sets an expiry
        on its per-run state.
        """

        client = self._redis_client()
        key = self._state_key(run_id)
        if client is not None:
            ttl = client.ttl(key)
            try:
                return int(ttl)
            except Exception:
                return None

        exp = self._local_expirations.get(run_id)
        if exp is None:
            return None
        remaining = int(max(0, exp - time.time()))
        return remaining

    def _make_envelope(self, original: Message, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Construct a MessageEnvelope-like dict for publishing to a stream."""

        envelope = MessageEnvelope(
            message_id=str(uuid4()),
            pipeline_run_id=original.pipeline_run_id or payload.get("pipeline_run_id", ""),
            trigger_type=original.trigger_type or original.data.get("trigger_type", "manual"),
            ticker=original.ticker or original.data.get("ticker", ""),
            timestamp=datetime.now(timezone.utc).isoformat(),
            payload=payload,
            metadata=dict(original.metadata or {}),
        )
        return envelope.model_dump()


__all__ = ["Arbiter"]
