"""Phase 15 unit tests for the bus, router, and EDGAR dedupe path."""

from __future__ import annotations

import importlib
import json
import sys
from types import SimpleNamespace

import fakeredis
import pytest
import responses
from sqlalchemy import create_engine, text


ATOM_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>{title}</title>
    <id>urn:tag:sec.gov,2008:accession-number={accession}</id>
    <updated>2026-05-22T12:00:00Z</updated>
    <summary>Ticker: {ticker}</summary>
    <category term="{ticker}" label="ticker"/>
    <link rel="alternate" href="https://www.sec.gov/Archives/edgar/data/320193/{accession_no_dashes}/{accession}-index.htm" />
  </entry>
</feed>
"""


def _reload_router_modules(monkeypatch: pytest.MonkeyPatch, tmp_path) -> tuple[object, object, str]:
    """Reload the routing modules against a dedicated SQLite database."""

    db_url = f"sqlite:///{tmp_path / 'router.db'}"
    monkeypatch.setenv("AIDER_DATABASE_URL", db_url)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    monkeypatch.setenv("FRED_API_KEY", "dummy")
    monkeypatch.setenv("SEC_USER_AGENT", "Test User test@example.com")
    monkeypatch.setenv("ENV", "development")

    for name in ["llm.router", "llm.claude_client", "llm.ollama_client", "core.config"]:
        if name in sys.modules:
            del sys.modules[name]

    router_mod = importlib.import_module("llm.router")
    claude_mod = importlib.import_module("llm.claude_client")
    return router_mod, claude_mod, db_url


def _prepare_llm_ledger(db_url: str) -> None:
    """Create the minimal LLM ledger schema for router tests."""

    engine = create_engine(db_url, future=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS llm_calls ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "run_id TEXT,"
                "agent TEXT,"
                "provider TEXT,"
                "model TEXT,"
                "prompt TEXT,"
                "response TEXT,"
                "confidence REAL,"
                "cost_usd REAL,"
                "input_tokens INTEGER,"
                "output_tokens INTEGER,"
                "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                ")"
            )
        )


def _reload_edgar_modules(monkeypatch: pytest.MonkeyPatch, tmp_path) -> tuple[object, object, str]:
    """Reload the EDGAR watcher modules against a dedicated SQLite database."""

    db_url = f"sqlite:///{tmp_path / 'edgar.db'}"
    monkeypatch.setenv("AIDER_DATABASE_URL", db_url)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    monkeypatch.setenv("FRED_API_KEY", "dummy")
    monkeypatch.setenv("SEC_USER_AGENT", "Test User test@example.com")
    monkeypatch.setenv("ENV", "development")

    for name in ["triggers.edgar_watcher", "db.edgar_triggers", "core.config"]:
        if name in sys.modules:
            del sys.modules[name]

    bus_mod = importlib.import_module("core.bus")
    watcher_mod = importlib.import_module("triggers.edgar_watcher")
    return bus_mod, watcher_mod, db_url


def _create_edgar_tables(db_url: str) -> None:
    """Create the tables needed by the EDGAR watcher test."""

    engine = create_engine(db_url, future=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS coverage_universe ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "ticker TEXT UNIQUE NOT NULL,"
                "added_at TEXT,"
                "notes TEXT"
                ")"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS edgar_triggers ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "accession_number TEXT NOT NULL UNIQUE,"
                "run_id TEXT,"
                "ticker TEXT,"
                "form_type TEXT,"
                "fiscal_year INTEGER,"
                "fiscal_period TEXT,"
                "filed_at TEXT,"
                "fetched_at TEXT DEFAULT CURRENT_TIMESTAMP"
                ")"
            )
        )


def _seed_coverage(db_url: str, tickers: list[str]) -> None:
    """Insert tickers into the EDGAR coverage universe."""

    engine = create_engine(db_url, future=True)
    with engine.begin() as connection:
        for ticker in tickers:
            connection.execute(text("INSERT INTO coverage_universe (ticker) VALUES (:ticker)"), {"ticker": ticker})


def _feed_xml(ticker: str, accession: str, title: str | None = None) -> str:
    """Render a tiny Atom feed with one EDGAR entry."""

    accession_no_dashes = accession.replace("-", "")
    return ATOM_FEED.format(
        ticker=ticker,
        accession=accession,
        accession_no_dashes=accession_no_dashes,
        title=title or f"{ticker} {accession}",
    )


def test_edgar_duplicate_not_retriggered(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """A repeated accession should only publish one trigger event."""

    bus_mod, watcher_mod, db_url = _reload_edgar_modules(monkeypatch, tmp_path)
    _create_edgar_tables(db_url)
    _seed_coverage(db_url, ["AAPL"])

    bus = bus_mod.RedisStreamsBus(fakeredis.FakeRedis(), db_url=db_url)
    watcher = watcher_mod.EdgarWatcher(bus=bus, db=create_engine(db_url), settings=importlib.import_module("core.config").settings)
    feed = _feed_xml("AAPL", "0000320193-26-000010", title="AAPL 8-K Filing")

    with responses.RequestsMock() as mocked:
        for form_type in ("8-K", "10-Q", "10-K"):
            mocked.add(
                responses.GET,
                f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type={form_type}&dateb=&owner=include&count=40&search_text=&output=atom",
                body=feed,
                status=200,
                content_type="application/atom+xml",
            )
        monkeypatch.setattr(watcher_mod.time, "sleep", lambda *_args, **_kwargs: None)
        watcher.poll()
        watcher.poll()

    assert bus.get_stream_length("trigger:events") == 1
    with create_engine(db_url).connect() as connection:
        count = connection.execute(
            text("SELECT COUNT(*) FROM edgar_triggers WHERE accession_number = '0000320193-26-000010'")
        ).scalar_one()
    assert count == 1


def test_confidence_gate_escalates(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Low Ollama confidence should escalate the router to Claude."""

    router_mod, claude_mod, db_url = _reload_router_modules(monkeypatch, tmp_path)
    _prepare_llm_ledger(db_url)

    calls = {"ollama": 0, "claude": 0}

    def fake_ollama(self, system_prompt, user_prompt, response_schema=None, max_tokens=1000, model=None):
        """Return a low-confidence Ollama payload."""

        calls["ollama"] += 1
        return {
            "regime": "bull",
            "confidence": 0.4,
            "sector_overweights": {"Technology": 0.4},
            "reasoning": "Supportive backdrop but confidence is low.",
        }

    def fake_claude(self, system_prompt, user_prompt, response_schema=None, max_tokens=1000, model=None, log_call=True):
        """Return a deterministic Claude response."""

        calls["claude"] += 1
        return {
            "regime": "bull",
            "confidence": 0.94,
            "sector_overweights": {"Technology": 0.5},
            "reasoning": "Claude provides the final structured answer.",
        }

    monkeypatch.setattr("llm.ollama_client.OllamaClient.generate", fake_ollama)
    monkeypatch.setattr(claude_mod.ClaudeClient, "complete", fake_claude)

    result = router_mod.call_llm(
        agent_name="rs1_macro",
        system_prompt="system",
        user_prompt="user",
        response_schema={
            "type": "object",
            "required": ["regime", "confidence", "sector_overweights", "reasoning"],
            "properties": {
                "regime": {"type": "string"},
                "confidence": {"type": "number"},
                "sector_overweights": {"type": "object"},
                "reasoning": {"type": "string"},
            },
        },
        settings=SimpleNamespace(
            ANTHROPIC_API_KEY="test-key",
            OLLAMA_HOST="http://ollama.local",
            OLLAMA_MODEL="gemma4:e4b",
            DATABASE_URL=db_url,
            DAILY_CLAUDE_SPEND_LIMIT_USD=10.0,
            CONFIDENCE_THRESHOLD=0.75,
            CLAUDE_MODEL="claude-sonnet-4-20250514",
        ),
    )

    assert calls["ollama"] == 1
    assert calls["claude"] == 1
    assert result["reasoning"] == "Claude provides the final structured answer."


def test_spend_limit_blocks_claude(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """The Claude client should fail fast when the daily spend limit is hit."""

    router_mod, claude_mod, db_url = _reload_router_modules(monkeypatch, tmp_path)
    _prepare_llm_ledger(db_url)

    engine = create_engine(db_url, future=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO llm_calls (run_id, agent, provider, model, prompt, response, confidence, cost_usd, created_at) "
                "VALUES ('run-1', 'pm1_thesis', 'anthropic', 'claude-sonnet-4-20250514', 'prompt', 'response', 1.0, 10.0, CURRENT_TIMESTAMP)"
            )
        )

    class FailAnthropic:
        """Guard against network access when the spend limit should stop the call."""

        def __init__(self, *args, **kwargs):
            raise AssertionError("Anthropic should not be reached once the spend limit is hit")

    monkeypatch.setattr(claude_mod, "Anthropic", FailAnthropic)

    with pytest.raises(Exception) as exc_info:
        router_mod.call_llm(
            agent_name="pm1_thesis",
            system_prompt="system",
            user_prompt="user",
            response_schema={"type": "object", "required": ["response"]},
            settings=SimpleNamespace(
                ANTHROPIC_API_KEY="test-key",
                OLLAMA_HOST="http://ollama.local",
                OLLAMA_MODEL="gemma4:e4b",
                DATABASE_URL=db_url,
                DAILY_CLAUDE_SPEND_LIMIT_USD=10.0,
                CONFIDENCE_THRESHOLD=0.75,
                CLAUDE_MODEL="claude-sonnet-4-20250514",
            ),
        )

    assert exc_info.value.__class__.__name__ == "SpendLimitError"