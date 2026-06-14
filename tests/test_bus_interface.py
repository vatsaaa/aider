"""Tests for the Bus abstraction and InMemoryBus implementation."""

from __future__ import annotations

from core.bus import InMemoryBus


def test_inmemorybus_send_and_read():
    bus = InMemoryBus()
    msg_id = bus.send("stage:rs1:output", {"x": 1})
    assert isinstance(msg_id, str)

    msgs = bus.read("stage:rs1:output", count=1)
    assert len(msgs) == 1
    assert msgs[0]["id"] == msg_id
    assert msgs[0]["message"]["x"] == 1

    # After read the stream should be empty
    assert bus.read("stage:rs1:output", count=1) == []
