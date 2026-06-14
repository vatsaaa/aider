"""Entrypoint that waits for Redis/Postgres to be available before starting monitor.

This avoids shell tooling dependencies in the container and provides a
deterministic startup sequence for the orchestrator-monitor service.
"""
from __future__ import annotations

import os
import socket
import sys
import time
from typing import Tuple


def _wait_for(host: str, port: int, timeout: int = 60) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except Exception:
            time.sleep(1)
    return False


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    redis_host = os.getenv("REDIS_HOST", "redis")
    redis_port = int(os.getenv("REDIS_PORT", "6379"))
    pg_host = os.getenv("POSTGRES_HOST", "postgres")
    pg_port = int(os.getenv("POSTGRES_PORT", "5432"))
    timeout = int(os.getenv("WAIT_TIMEOUT", "60"))

    ok_redis = _wait_for(redis_host, redis_port, timeout=timeout)
    ok_pg = _wait_for(pg_host, pg_port, timeout=timeout)

    if not (ok_redis and ok_pg):
        print("dependencies did not come up within timeout", file=sys.stderr)
        return 2

    # import and run the monitor module now that dependencies are ready
    try:
        from orchestrator.monitor import main as monitor_main

        return monitor_main(argv)
    except Exception as exc:
        print("failed to start monitor:", exc, file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
