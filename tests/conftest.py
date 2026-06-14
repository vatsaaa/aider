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


@pytest.fixture(autouse=True)
def _default_test_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Seed the minimum environment required by the runtime modules.

    Individual tests can override these defaults with their own monkeypatch
    calls when they need a different database URL or runtime mode.
    """

    defaults = {
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
    for key, value in defaults.items():
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