"""Process entrypoint for running a single pipeline agent or daemon.

Each Docker Compose service runs `python -m core.runner <service>`. The runner
waits for Redis and PostgreSQL, wires the shared `RedisStreamsBus`, SQLAlchemy
engine, and settings into the requested agent, and blocks in its run loop.
"""

from __future__ import annotations

import argparse
import importlib
import socket
import sys
import time
from typing import Any, Callable, Protocol
from urllib.parse import urlparse

from sqlalchemy.engine import make_url

REDIS_SOCKET_TIMEOUT_SECONDS = 30

AGENTS: dict[str, str] = {
    "rs1": "agents.rs1_macro:RS1MacroAgent",
    "rs2": "agents.rs2_sector:RS2SectorAgent",
    "rs3": "agents.rs3_screen:RS3ScreenAgent",
    "av1": "agents.av1_data:AV1DataAgent",
    "av2": "agents.av2_model:AV2ModelAgent",
    "av3": "agents.av3_valuation:AV3ValuationAgent",
    "pm1": "agents.pm1_thesis:PM1ThesisAgent",
    "quant_critic": "critics.quant_critic:QuantCritic",
    "logic_critic": "critics.logic_critic:LogicCritic",
    "data_critic": "critics.data_critic:DataCritic",
    "arbiter": "critics.arbiter:Arbiter",
    "pm2": "agents.pm2_compliance:PM2ComplianceAgent",
    "pm3": "agents.pm3_publisher:PM3PublisherAgent",
    "monitor": "monitor.coverage_loop:CoverageMonitor",
}


class Runnable(Protocol):
    """Anything with a blocking `run()` loop."""

    def run(self) -> None:
        """Block and process work until interrupted."""


def resolve(name: str) -> type:
    """Import and return the class registered under `name`."""

    if name not in AGENTS:
        raise KeyError(f"unknown agent {name!r}; expected one of {', '.join(sorted(AGENTS))}")
    module_name, class_name = AGENTS[name].split(":")
    return getattr(importlib.import_module(module_name), class_name)


def _endpoint_from_redis_url(url: str) -> tuple[str, int]:
    """Return (host, port) from a Redis URL."""

    parsed = urlparse(url)
    return parsed.hostname or "localhost", parsed.port or 6379


def _endpoint_from_db_url(url: str) -> tuple[str, int]:
    """Return (host, port) from a SQLAlchemy database URL."""

    parsed = make_url(url)
    return parsed.host or "localhost", int(parsed.port or 5432)


def wait_for_tcp(host: str, port: int, timeout_seconds: float, sleep: Callable[[float], None] = time.sleep) -> bool:
    """Poll until a TCP connection to host:port succeeds or the timeout elapses."""

    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            if time.monotonic() >= deadline:
                return False
            sleep(1)


def wait_for_dependencies(redis_url: str, database_url: str, timeout_seconds: float) -> None:
    """Block until Redis and PostgreSQL accept connections, raising `RuntimeError` on timeout."""

    endpoints = [("redis", _endpoint_from_redis_url(redis_url))]
    if not make_url(database_url).get_backend_name().startswith("sqlite"):
        endpoints.append(("postgres", _endpoint_from_db_url(database_url)))
    for label, (host, port) in endpoints:
        if not wait_for_tcp(host, port, timeout_seconds):
            raise RuntimeError(f"{label} at {host}:{port} not reachable after {timeout_seconds:.0f}s")


def build(name: str, settings: Any) -> Runnable:
    """Construct the agent registered under `name` with production bus, database and settings."""

    import redis
    from sqlalchemy import create_engine

    from core.bus import RedisStreamsBus

    agent_cls = resolve(name)
    engine = create_engine(settings.AIDER_DATABASE_URL, future=True, pool_pre_ping=True)
    # redis-py >= 6 defaults socket_timeout to 5s, which equals the 5s XREADGROUP block and aborts idle reads
    redis_client = redis.Redis.from_url(
        settings.REDIS_URL,
        socket_timeout=REDIS_SOCKET_TIMEOUT_SECONDS,
        socket_connect_timeout=5,
        health_check_interval=30,
    )
    bus = RedisStreamsBus(redis_client, db_url=settings.AIDER_DATABASE_URL)
    return agent_cls(bus=bus, db=engine, settings=settings)


def build_parser() -> argparse.ArgumentParser:
    """Return the CLI parser for `python -m core.runner`."""

    parser = argparse.ArgumentParser(prog="python -m core.runner", description="Run one pipeline agent or daemon.")
    parser.add_argument("agent", choices=sorted(AGENTS), help="Agent/service to run")
    parser.add_argument("--wait-timeout", type=float, default=60.0, help="Seconds to wait for Redis and PostgreSQL")
    parser.add_argument("--no-wait", action="store_true", help="Skip waiting for Redis and PostgreSQL")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint: wait for dependencies, build the agent, and run it until interrupted."""

    args = build_parser().parse_args(argv)

    from core.config import settings

    try:
        if not args.no_wait:
            wait_for_dependencies(settings.REDIS_URL, settings.AIDER_DATABASE_URL, args.wait_timeout)
        runnable = build(args.agent, settings)
    except Exception as exc:
        print(f"failed to start {args.agent}: {exc}", file=sys.stderr)
        return 2

    try:
        runnable.run()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
