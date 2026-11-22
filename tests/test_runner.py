"""Tests for the agent process entrypoint and the Docker Compose service commands."""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Any

import pytest
import yaml

from core import runner
from core.bus import InMemoryBus


ROOT = Path(__file__).resolve().parents[1]


def _is_stream_agent(cls: type) -> bool:
    """Return True for BaseAgent subclasses (by name, since other tests reload `core.agent_base`)."""

    return any(base.__name__ == "BaseAgent" for base in cls.__mro__)


@pytest.mark.parametrize("name", sorted(runner.AGENTS))
def test_every_registered_agent_resolves(name: str) -> None:
    """Each registry entry imports and exposes a blocking `run` loop."""

    agent_cls = runner.resolve(name)
    assert callable(getattr(agent_cls, "run", None))
    assert _is_stream_agent(agent_cls) is (name != "monitor")


def test_stream_agents_constructible_with_bus_db_settings() -> None:
    """Every BaseAgent in the registry accepts the (bus, db, settings) wiring used by `build`."""

    from sqlalchemy import create_engine

    from core.config import settings

    engine = create_engine("sqlite:///:memory:", future=True)
    for name in runner.AGENTS:
        agent_cls = runner.resolve(name)
        if not _is_stream_agent(agent_cls):
            continue
        agent = agent_cls(bus=InMemoryBus(), db=engine, settings=settings)
        assert agent.stream_out or agent.stream_in


def test_unknown_agent_rejected() -> None:
    """Unknown names fail fast instead of starting an idle container."""

    with pytest.raises(KeyError):
        runner.resolve("nope")
    with pytest.raises(SystemExit):
        runner.main(["nope"])


def test_main_waits_builds_and_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """`main` waits for dependencies, builds the named agent, and enters its run loop."""

    calls: list[Any] = []

    class FakeAgent:
        """Stand-in agent recording that `run` was called."""

        def run(self) -> None:
            """Record the call."""

            calls.append("run")

    monkeypatch.setattr(runner, "wait_for_dependencies", lambda redis_url, db_url, timeout: calls.append(("wait", timeout)))
    monkeypatch.setattr(runner, "build", lambda name, settings: calls.append(("build", name)) or FakeAgent())

    assert runner.main(["av1", "--wait-timeout", "5"]) == 0
    assert calls == [("wait", 5.0), ("build", "av1"), "run"]


def test_main_returns_error_when_dependencies_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """A dependency timeout exits non-zero so Docker restarts the container."""

    def fail(*args: Any) -> None:
        raise RuntimeError("redis at redis:6379 not reachable")

    monkeypatch.setattr(runner, "wait_for_dependencies", fail)
    assert runner.main(["pm1"]) == 2


def test_wait_for_tcp(monkeypatch: pytest.MonkeyPatch) -> None:
    """`wait_for_tcp` succeeds against a listening socket and times out against a closed port."""

    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    try:
        assert runner.wait_for_tcp("127.0.0.1", port, timeout_seconds=1) is True
    finally:
        server.close()
    assert runner.wait_for_tcp("127.0.0.1", port, timeout_seconds=0, sleep=lambda _: None) is False


def test_wait_for_dependencies_parses_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hosts and ports come from REDIS_URL and the database URL; SQLite needs no wait."""

    seen: list[tuple[str, int]] = []
    monkeypatch.setattr(runner, "wait_for_tcp", lambda host, port, timeout: seen.append((host, port)) or True)

    runner.wait_for_dependencies("redis://redis:6380/0", "postgresql+psycopg2://u:p@postgres:5433/db", 10)
    runner.wait_for_dependencies("redis://localhost", "sqlite:///:memory:", 10)
    assert seen == [("redis", 6380), ("postgres", 5433), ("localhost", 6379)]

    monkeypatch.setattr(runner, "wait_for_tcp", lambda host, port, timeout: False)
    with pytest.raises(RuntimeError, match="redis"):
        runner.wait_for_dependencies("redis://redis:6379", "sqlite://", 1)


def test_compose_services_have_startup_commands() -> None:
    """Every service built from the repo image has a command, and agent commands name a registered agent."""

    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    built = {name: svc for name, svc in compose["services"].items() if svc.get("build")}
    missing = [name for name, svc in built.items() if not svc.get("command")]
    assert missing == []

    runner_services = {name: svc["command"].split() for name, svc in built.items() if "core.runner" in svc["command"]}
    assert set(runner_services) == set(runner.AGENTS)
    for name, command in runner_services.items():
        assert command[:3] == ["python", "-m", "core.runner"]
        assert command[3] == name


def test_build_uses_socket_timeout_longer_than_block(monkeypatch: pytest.MonkeyPatch) -> None:
    """`build` configures a Redis socket timeout longer than the agents' 5s blocking reads."""

    import redis

    captured: dict[str, Any] = {}
    real_from_url = redis.Redis.from_url

    def fake_from_url(url: str, **kwargs: Any) -> Any:
        captured.update(kwargs)
        return real_from_url(url, **kwargs)

    monkeypatch.setattr(redis.Redis, "from_url", fake_from_url)
    settings = type("S", (), {"AIDER_DATABASE_URL": "sqlite:///:memory:", "REDIS_URL": "redis://localhost:6379/0", "SEC_USER_AGENT": "x x@example.com"})()

    agent = runner.build("av2", settings)

    assert captured["socket_timeout"] > 5
    assert type(agent).__name__ == "AV2ModelAgent"
