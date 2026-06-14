"""Test that runs the DB migration and verifies all expected tables exist.

This test requires a PostgreSQL instance accessible via the `DATABASE_URL`
environment variable. If `DATABASE_URL` is not set the test will be skipped.
"""

from __future__ import annotations

import importlib
import os
import sys
from typing import List

import pytest
from sqlalchemy import create_engine, text


EXPECTED_TABLES = [
    "pipeline_runs",
    "data_packages",
    "financial_models",
    "reports",
    "audit_log",
    "dlq_entries",
    "llm_calls",
    "coverage_universe",
    "price_snapshots",
    "edgar_triggers",
]


def _clear_core_modules():
    for name in list(sys.modules.keys()):
        if name.startswith("core.config") or name.startswith("core."):
            del sys.modules[name]


def test_schema_all_tables_exist(monkeypatch, tmp_path):
    """Run migration then assert all EXPECTED_TABLES exist in information_schema."""

    database_url = os.getenv("AIDER_DATABASE_URL")
    if not database_url:
        pytest.skip("AIDER_DATABASE_URL not set; skipping migration integration test")
    if database_url == "sqlite:///:memory:":
        database_url = f"sqlite:///{tmp_path / 'schema.db'}"

    # Provide minimal required env vars for core.config validation
    required = [
        "ANTHROPIC_API_KEY",
        "REDIS_URL",
        "FRED_API_KEY",
        "SEC_USER_AGENT",
    ]
    for v in required:
        monkeypatch.setenv(v, "dummy")

    monkeypatch.setenv("AIDER_DATABASE_URL", database_url)

    # Ensure fresh imports of core.config
    _clear_core_modules()
    # Import and run migration
    migrate = importlib.import_module("db.migrate")
    migrate.run_migration()

    # Connect and query tables
    engine = create_engine(database_url)
    with engine.connect() as conn:
        if engine.dialect.name == "sqlite":
            rows = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
        else:
            rows = conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
                )
            ).fetchall()
        existing = {r[0] for r in rows}

    missing: List[str] = [t for t in EXPECTED_TABLES if t not in existing]
    assert not missing, f"Missing tables after migration: {missing}"
