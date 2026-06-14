"""Tests for the SEC EDGAR watcher."""

from __future__ import annotations

import importlib
import json
import sys

import fakeredis
import responses
from sqlalchemy import create_engine, text


ATOM_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>{title}</title>
    <id>urn:tag:sec.gov,2008:accession-number={accession}</id>
    <updated>2026-05-22T12:00:00Z</updated>
    <summary>{summary}</summary>
    <category term="{ticker}" label="ticker"/>
    <link rel="alternate" href="https://www.sec.gov/Archives/edgar/data/320193/{accession_no_dashes}/{accession}-index.htm" />
  </entry>
</feed>
"""


def _reload_modules(monkeypatch, tmp_path):
    """Reload the watcher stack with a dedicated SQLite database."""

    db_url = f"sqlite:///{tmp_path / 'edgar.db'}"
    monkeypatch.setenv("AIDER_DATABASE_URL", db_url)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    monkeypatch.setenv("FRED_API_KEY", "dummy")
    monkeypatch.setenv("SEC_USER_AGENT", "Test User test@example.com")
    monkeypatch.setenv("ENV", "development")

    for name in ["triggers.edgar_watcher", "db.edgar_triggers", "core.config", "core", "db"]:
        if name in sys.modules:
            del sys.modules[name]

    core_bus = importlib.import_module("core.bus")
    watcher_mod = importlib.import_module("triggers.edgar_watcher")
    return core_bus, watcher_mod, db_url


def _create_tables(db_url: str) -> None:
    """Create the minimal tables needed by the watcher."""

    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE coverage_universe ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "ticker TEXT UNIQUE NOT NULL,"
                "added_at TEXT,"
                "notes TEXT)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE edgar_triggers ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "accession_number TEXT NOT NULL UNIQUE,"
                "run_id TEXT,"
                "ticker TEXT,"
                "form_type TEXT,"
                "fiscal_year INTEGER,"
                "fiscal_period TEXT,"
                "filed_at TEXT,"
                "fetched_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
        )


def _seed_coverage(db_url: str, tickers: list[str]) -> None:
    """Insert tickers into the coverage universe."""

    engine = create_engine(db_url)
    with engine.begin() as conn:
        for ticker in tickers:
            conn.execute(text("INSERT INTO coverage_universe (ticker) VALUES (:ticker)"), {"ticker": ticker})


def _feed_xml(ticker: str, accession: str, title: str | None = None, summary: str | None = None) -> str:
    """Render a tiny Atom feed with one EDGAR entry."""

    accession_no_dashes = accession.replace("-", "")
    return ATOM_FEED.format(
        ticker=ticker,
        accession=accession,
        accession_no_dashes=accession_no_dashes,
        title=title or f"{ticker} {accession}",
        summary=summary or f"Ticker: {ticker}",
    )


def test_edgar_watcher_publishes_m1(monkeypatch, tmp_path):
    """A covered filing should publish exactly one M1 event."""

    busmod, watcher_mod, db_url = _reload_modules(monkeypatch, tmp_path)
    _create_tables(db_url)
    _seed_coverage(db_url, ["AAPL"])
    bus = busmod.RedisStreamsBus(fakeredis.FakeRedis(), db_url=db_url)
    watcher = watcher_mod.EdgarWatcher(
        bus=bus,
        db=create_engine(db_url),
        settings=importlib.import_module("core.config").settings,
    )

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
        events = watcher.poll()

    assert len(events) == 1
    assert events[0].ticker == "AAPL"
    assert events[0].trigger_type == "8-K"
    assert bus.get_stream_length("trigger:events") == 1

    stream_entry = bus._client.xrange("trigger:events", count=1)[0][1]
    payload = json.loads(stream_entry[b"data"].decode())
    assert payload["ticker"] == "AAPL"
    assert payload["trigger_type"] == "8-K"


def test_edgar_watcher_deduplicates(monkeypatch, tmp_path):
    """The same accession number should only trigger once across polls."""

    busmod, watcher_mod, db_url = _reload_modules(monkeypatch, tmp_path)
    _create_tables(db_url)
    _seed_coverage(db_url, ["AAPL"])
    bus = busmod.RedisStreamsBus(fakeredis.FakeRedis(), db_url=db_url)
    watcher = watcher_mod.EdgarWatcher(
        bus=bus,
        db=create_engine(db_url),
        settings=importlib.import_module("core.config").settings,
    )

    feed = _feed_xml("AAPL", "0000320193-26-000010")

    with responses.RequestsMock() as mocked:
        for _ in range(2):
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
    with create_engine(db_url).connect() as conn:
        count = conn.execute(
            text("SELECT COUNT(*) FROM edgar_triggers WHERE accession_number = '0000320193-26-000010'")
        ).scalar_one()
        assert count == 1


def test_edgar_watcher_skips_uncovered_tickers(monkeypatch, tmp_path):
    """Uncovered tickers should not produce trigger events."""

    busmod, watcher_mod, db_url = _reload_modules(monkeypatch, tmp_path)
    _create_tables(db_url)
    _seed_coverage(db_url, ["AAPL"])
    bus = busmod.RedisStreamsBus(fakeredis.FakeRedis(), db_url=db_url)
    watcher = watcher_mod.EdgarWatcher(
        bus=bus,
        db=create_engine(db_url),
        settings=importlib.import_module("core.config").settings,
    )

    feed = _feed_xml("ZZZZ", "0000000000-26-000001")

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
        events = watcher.poll()

    assert events == []
    assert bus.get_stream_length("trigger:events") == 0


def test_edgar_watcher_sets_user_agent(monkeypatch, tmp_path):
    """Every SEC request should include the configured User-Agent header."""

    busmod, watcher_mod, db_url = _reload_modules(monkeypatch, tmp_path)
    _create_tables(db_url)
    _seed_coverage(db_url, ["AAPL"])
    bus = busmod.RedisStreamsBus(fakeredis.FakeRedis(), db_url=db_url)
    watcher = watcher_mod.EdgarWatcher(
        bus=bus,
        db=create_engine(db_url),
        settings=importlib.import_module("core.config").settings,
    )

    feed = _feed_xml("AAPL", "0000320193-26-000010")

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

        assert len(mocked.calls) == 3
        for call in mocked.calls:
            assert call.request.headers["User-Agent"] == "Test User test@example.com"


def test_edgar_watcher_deduplicates_by_fiscal_period(monkeypatch, tmp_path):
    """A new accession for the same ticker/form/fiscal period should not retrigger."""

    busmod, watcher_mod, db_url = _reload_modules(monkeypatch, tmp_path)
    _create_tables(db_url)
    _seed_coverage(db_url, ["AAPL"])
    bus = busmod.RedisStreamsBus(fakeredis.FakeRedis(), db_url=db_url)
    watcher = watcher_mod.EdgarWatcher(
        bus=bus,
        db=create_engine(db_url),
        settings=importlib.import_module("core.config").settings,
    )

    first_feed = _feed_xml(
        "AAPL",
        "0000320193-26-000010",
        title="AAPL 10-Q Filing",
        summary="For the quarter ended June 30, 2026",
    )
    second_feed = _feed_xml(
        "AAPL",
        "0000320193-26-000011",
        title="AAPL 10-Q Filing",
        summary="For the quarter ended June 30, 2026",
    )
    empty_feed = "<?xml version=\"1.0\" encoding=\"UTF-8\"?><feed xmlns=\"http://www.w3.org/2005/Atom\"></feed>"

    with responses.RequestsMock() as mocked:
        mocked.add(
            responses.GET,
            "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&dateb=&owner=include&count=40&search_text=&output=atom",
            body=empty_feed,
            status=200,
            content_type="application/atom+xml",
        )
        mocked.add(
            responses.GET,
            "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=10-Q&dateb=&owner=include&count=40&search_text=&output=atom",
            body=first_feed,
            status=200,
            content_type="application/atom+xml",
        )
        mocked.add(
            responses.GET,
            "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=10-K&dateb=&owner=include&count=40&search_text=&output=atom",
            body=empty_feed,
            status=200,
            content_type="application/atom+xml",
        )
        mocked.add(
            responses.GET,
            "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&dateb=&owner=include&count=40&search_text=&output=atom",
            body=empty_feed,
            status=200,
            content_type="application/atom+xml",
        )
        mocked.add(
            responses.GET,
            "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=10-Q&dateb=&owner=include&count=40&search_text=&output=atom",
            body=second_feed,
            status=200,
            content_type="application/atom+xml",
        )
        mocked.add(
            responses.GET,
            "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=10-K&dateb=&owner=include&count=40&search_text=&output=atom",
            body=empty_feed,
            status=200,
            content_type="application/atom+xml",
        )
        monkeypatch.setattr(watcher_mod.time, "sleep", lambda *_args, **_kwargs: None)
        watcher.poll()
        watcher.poll()

    assert bus.get_stream_length("trigger:events") == 1
    with create_engine(db_url).connect() as connection:
        count = connection.execute(
            text(
                "SELECT COUNT(*) FROM edgar_triggers WHERE ticker = 'AAPL' AND form_type = '10-Q' AND fiscal_year = 2026 AND fiscal_period = 'FY2026Q2'"
            )
        ).scalar_one()
    assert count == 1
