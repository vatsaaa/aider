"""Tests for the coverage universe seed and add-ticker scripts."""

from __future__ import annotations

import importlib
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"


def _create_tables(engine) -> None:
    """Create the minimal tables required for the scripts."""

    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE coverage_universe ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "ticker TEXT NOT NULL UNIQUE,"
                "added_at TEXT,"
                "notes TEXT"
                ")"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE price_snapshots ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "ticker TEXT NOT NULL,"
                "price REAL NOT NULL,"
                "snapped_at TEXT,"
                "source TEXT"
                ")"
            )
        )


@pytest.fixture()
def coverage_engine(tmp_path):
    """Provide a SQLite engine with the tables needed by the scripts."""

    db_path = tmp_path / "coverage.db"
    engine = create_engine(f"sqlite:///{db_path}")
    _create_tables(engine)
    return engine


@pytest.fixture()
def seeded_settings(monkeypatch, coverage_engine):
    """Patch core.config to return a tiny settings object for scripts."""

    settings = SimpleNamespace(
        DATABASE_URL=str(coverage_engine.url),
        ANTHROPIC_API_KEY="dummy",
        OLLAMA_HOST="http://localhost:11434",
        OLLAMA_MODEL="gemma4:e4b",
        REDIS_URL="redis://localhost:6379",
        FRED_API_KEY="dummy",
        SEC_USER_AGENT="Test User test@example.com",
        GIT_REPO_PATH="./reports_audit",
        GIT_AUTHOR_NAME="Digital Analyst",
        GIT_AUTHOR_EMAIL="analyst@localhost",
        SMTP_HOST="mailhog",
        SMTP_PORT=1025,
        SMTP_USER=None,
        SMTP_PASSWORD=None,
        SMTP_FROM="analyst@localhost",
        SMTP_TO=[],
        DLQ_STREAM="dlq:failed",
        MAX_REVISION_ITERATIONS=3,
        DAILY_CLAUDE_SPEND_LIMIT_USD=10.0,
        CONFIDENCE_THRESHOLD=0.75,
        ENV="development",
    )
    monkeypatch.setitem(sys.modules, "core.config", SimpleNamespace(settings=settings))
    return settings


def test_seed_db_inserts_all_tickers(monkeypatch, coverage_engine, seeded_settings):
    """The seed script should insert all 50 coverage rows."""

    import scripts.seed_db as seed_db

    monkeypatch.setattr(seed_db, "get_price", lambda ticker: 100.0)
    rows = seed_db.load_coverage_universe(ROOT / "config" / "coverage_universe.yaml")
    assert len(rows) == 50

    seed_db.seed_database(str(coverage_engine.url), rows)

    with coverage_engine.connect() as connection:
        count = connection.execute(text("SELECT COUNT(*) FROM coverage_universe")).scalar_one()

    assert count == 50


def test_seed_db_is_idempotent(monkeypatch, coverage_engine, seeded_settings):
    """Running the seed script twice should not duplicate coverage rows."""

    import scripts.seed_db as seed_db

    monkeypatch.setattr(seed_db, "get_price", lambda ticker: 100.0)
    rows = seed_db.load_coverage_universe(ROOT / "config" / "coverage_universe.yaml")

    seed_db.seed_database(str(coverage_engine.url), rows)
    seed_db.seed_database(str(coverage_engine.url), rows)

    with coverage_engine.connect() as connection:
        count = connection.execute(text("SELECT COUNT(*) FROM coverage_universe")).scalar_one()

    assert count == 50


def test_add_ticker_inserts_row(coverage_engine, seeded_settings):
    """The add-ticker CLI should insert a new coverage row."""

    import scripts.add_ticker as add_ticker

    inserted = add_ticker.add_ticker(
        str(coverage_engine.url),
        "NVDA",
        "Technology",
        ["AMD", "INTC", "QCOM", "AVGO"],
        5.0,
    )

    assert inserted is True
    with coverage_engine.connect() as connection:
        row = connection.execute(text("SELECT ticker FROM coverage_universe WHERE ticker = 'NVDA'" )).fetchone()
    assert row is not None
    assert row[0] == "NVDA"


def test_add_ticker_rejects_duplicate(capsys, coverage_engine, seeded_settings):
    """The add-ticker CLI should warn and exit cleanly on duplicate rows."""

    with coverage_engine.begin() as connection:
        connection.execute(
            text("INSERT INTO coverage_universe (ticker, added_at, notes) VALUES ('AAPL', CURRENT_TIMESTAMP, 'existing')")
        )

    import scripts.add_ticker as add_ticker

    inserted = add_ticker.add_ticker(
        str(coverage_engine.url),
        "AAPL",
        "Technology",
        ["MSFT", "NVDA", "GOOGL"],
        5.0,
    )

    captured = capsys.readouterr().out
    assert inserted is False
    assert "already exists" in captured
