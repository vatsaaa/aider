"""Pytest support for the Digital Equity Analyst test harness.

This module keeps the repository root importable and provides the fixtures
required by the Phase 15 test suite: a fakeredis-backed bus, a unit-test
database handle, a mocked LLM router, and file-backed fixtures for the AAPL
10-K excerpt and the sample M7 payload.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

import fakeredis
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool


ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = ROOT / "tests" / "fixtures"

root_str = str(ROOT)
if root_str not in sys.path:
    sys.path.insert(0, root_str)


_TEST_ENV_DEFAULTS = {
        "ANTHROPIC_API_KEY": "dummy",
        "AIDER_DATABASE_URL": "sqlite:///:memory:",
        "REDIS_URL": "redis://localhost:6379",
        "FRED_API_KEY": "dummy",
        "SEC_USER_AGENT": "Test User test@example.com",
        "ENV": "development",
        "MAX_REVISION_ITERATIONS": "3",
        "CONFIDENCE_THRESHOLD": "0.75",
        "DAILY_CLAUDE_SPEND_LIMIT_USD": "10.0",
        "SMTP_HOST": "mailhog",
        "SMTP_PORT": "1025",
        "SMTP_FROM": "analyst@localhost",
        "SMTP_TO": "alpha@localhost,beta@localhost",
        "GIT_REPO_PATH": str(ROOT / "reports_audit"),
        "GIT_AUTHOR_NAME": "Digital Analyst",
        "GIT_AUTHOR_EMAIL": "analyst@localhost",
}

# Test modules import `core.config` at collection time, before any fixture runs,
# so the required variables must exist in the process environment up front.
for _key, _value in _TEST_ENV_DEFAULTS.items():
    os.environ.setdefault(_key, _value)


@pytest.fixture(autouse=True)
def _default_test_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Seed the minimum environment required by the runtime modules.

    Individual tests can override these defaults with their own monkeypatch
    calls when they need a different database URL or runtime mode.
    """

    for key, value in _TEST_ENV_DEFAULTS.items():
        monkeypatch.setenv(key, value)


@pytest.fixture()
def fake_bus(tmp_path: Path):
    """Return a fakeredis-backed RedisStreamsBus with a writable DLQ table."""

    from core.bus import RedisStreamsBus

    db_path = tmp_path / "fake_bus.db"
    db_url = f"sqlite:///{db_path}"
    engine = create_engine(db_url, future=True)
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS dlq_entries ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "run_id TEXT, stream TEXT NOT NULL, message_id TEXT, reason TEXT, payload TEXT, created_at TEXT)"
            )
        )

    return RedisStreamsBus(fakeredis.FakeRedis(), db_url=db_url)


@pytest.fixture()
def test_db() -> Any:
    """Return a SQLAlchemy engine for unit tests.

    Unit tests default to an isolated in-memory SQLite engine. If the caller
    exports TEST_DB_URL, the fixture connects to that external database
    instead so integration-style tests can exercise the real backend.
    """

    test_db_url = os.getenv("TEST_DB_URL")
    if test_db_url:
        return create_engine(test_db_url, future=True)
    return create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


@pytest.fixture()
def mock_llm_router(monkeypatch: pytest.MonkeyPatch) -> Callable[..., dict[str, Any] | str]:
    """Patch the LLM router to return deterministic canned responses.

    The fixture patches the implementation module used by the agents,
    `aider.llm.router`, so calls from `BaseAgent.call_llm()` never reach a
    real provider during tests.
    """

    def fake_call_llm(*, agent_name: str, **kwargs: Any) -> dict[str, Any] | str:
        """Return a canned response keyed by agent name."""

        if agent_name == "rs1_macro":
            return {
                "regime": "recovery",
                "sector_overweights": ["Technology"],
                "sector_underweights": ["Utilities", "Consumer Staples", "Healthcare"],
                "confidence": 0.91,
                "reasoning": "Mock macro response.",
            }
        if agent_name == "pm1_thesis":
            return {
                "investment_thesis": "Mock thesis text.",
                "business_model": "Mock business model text.",
                "earnings_review": "Mock earnings review text.",
                "risk_factors": "Mock risk factors text.",
                "dcf_detail": "Mock DCF detail text.",
                "peer_comp_table": "Mock peer comparison text.",
                "financial_summary_rows": [],
                "scenarios": {"bear": "Mock", "base": "Mock", "bull": "Mock"},
                "sensitivity_table": {},
                "sensitivity_growth_rates": [],
            }
        return {"response": "mocked"}

    import llm.router as router_module

    monkeypatch.setattr(router_module, "call_llm", fake_call_llm)
    return fake_call_llm


@pytest.fixture()
def aapl_10k_fixture() -> str:
    """Load the bundled AAPL 10-K excerpt as text."""

    return (FIXTURES_DIR / "aapl_10k_excerpt.xml").read_text(encoding="utf-8")


@pytest.fixture()
def sample_m7_fixture() -> dict[str, Any]:
    """Load the sample M7 valuation payload from JSON."""

    return json.loads((FIXTURES_DIR / "sample_m7.json").read_text(encoding="utf-8"))

_PROJECT_PACKAGES = frozenset(
    path.name
    for path in ROOT.iterdir()
    if path.is_dir() and path.name != "tests" and not path.name.startswith(".") and any(path.glob("*.py"))
)


def _is_project_module(name: str) -> bool:
    """Return True for modules that belong to this repository (not tests or third-party code)."""

    return name.split(".", 1)[0] in _PROJECT_PACKAGES


@pytest.fixture(autouse=True)
def _restore_project_modules() -> Any:
    """Undo any `sys.modules` purges a test performs so later tests see the modules they imported.

    Many tests delete and re-import project modules to pick up patched
    environment variables. Without restoring them, a later test's
    collection-time imports (e.g. `FatalError`) no longer match the classes the
    re-imported code raises, making results depend on test order.
    """

    saved = {name: module for name, module in sys.modules.items() if _is_project_module(name)}
    yield
    for name in [name for name in sys.modules if _is_project_module(name) and name not in saved]:
        del sys.modules[name]
    sys.modules.update(saved)
    for name, module in saved.items():
        parent_name, _, child = name.rpartition(".")
        parent = saved.get(parent_name)
        if parent is not None:
            setattr(parent, child, module)


class NetworkAccessBlocked(OSError):
    """Raised when a test tries to open a connection to a non-local host."""


def _is_local_address(address: Any) -> bool:
    """Return True for loopback / Unix-socket addresses that tests may use (local Redis, Postgres, Docker)."""

    if not isinstance(address, tuple):
        return True
    host = str(address[0])
    return host in {"localhost", "::1", "0.0.0.0"} or host.startswith("127.")


@pytest.fixture(autouse=True)
def _block_external_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any outbound connection so tests never depend on live SEC, FRED, Yahoo or LLM services."""

    import socket

    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def guarded_connect(sock: socket.socket, address: Any) -> Any:
        if not _is_local_address(address):
            raise NetworkAccessBlocked(f"tests must not access the network: {address!r}")
        return real_connect(sock, address)

    def guarded_connect_ex(sock: socket.socket, address: Any) -> Any:
        if not _is_local_address(address):
            raise NetworkAccessBlocked(f"tests must not access the network: {address!r}")
        return real_connect_ex(sock, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)


@pytest.fixture
def yfinance_peer_info(monkeypatch: pytest.MonkeyPatch) -> dict[str, dict[str, float]]:
    """Patch `yfinance.Ticker` to serve peer `info` dicts from `tests/fixtures/yfinance_peer_info.json`."""

    info_by_ticker = json.loads((FIXTURES_DIR / "yfinance_peer_info.json").read_text(encoding="utf-8"))

    class FixtureTicker:
        """Offline stand-in for `yfinance.Ticker` backed by the fixture file."""

        def __init__(self, ticker: str) -> None:
            self.info = dict(info_by_ticker.get(ticker, {}))

    monkeypatch.setattr("yfinance.Ticker", FixtureTicker)
    return info_by_ticker
