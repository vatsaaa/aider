"""Phase 15 unit tests for valuation helpers."""

from __future__ import annotations

import json

from sqlalchemy import text


def test_dcf_terminal_value_sensitivity() -> None:
    """A normal five-year FCF stream should produce a dominant terminal value."""

    from models.valuation import compute_dcf

    result = compute_dcf([100.0, 110.0, 120.0, 130.0, 140.0], 0.10)
    assert 0.60 <= result["terminal_value_share"] <= 0.80


def test_peer_multiple_wrong_sector(test_db) -> None:
    """Banking names should use price-to-book rather than EV/EBITDA."""

    from models.valuation import compute_peer_multiple

    with test_db.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS coverage_universe ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "ticker TEXT UNIQUE,"
                "added_at TEXT,"
                "notes TEXT"
                ")"
            )
        )
        connection.execute(text("DELETE FROM coverage_universe"))
        connection.execute(
            text("INSERT INTO coverage_universe (ticker, notes) VALUES (:ticker, :notes)"),
            {"ticker": "JPM", "notes": json.dumps({"sector": "Banking", "peers": ["BAC", "WFC"]})},
        )
        connection.execute(
            text("INSERT INTO coverage_universe (ticker, notes) VALUES (:ticker, :notes)"),
            {"ticker": "BAC", "notes": json.dumps({"sector": "Banking"})},
        )
        connection.execute(
            text("INSERT INTO coverage_universe (ticker, notes) VALUES (:ticker, :notes)"),
            {"ticker": "WFC", "notes": json.dumps({"sector": "Banking"})},
        )

    class DummyTicker:
        """Return fixed multiples for the peer lookup."""

        def __init__(self, ticker: str) -> None:
            self.info = {
                "priceToBook": 1.5 if ticker == "BAC" else 1.2,
                "enterpriseToEbitda": 8.0,
                "forwardPE": 9.0,
            }

    import yfinance

    original_ticker = yfinance.Ticker
    yfinance.Ticker = lambda ticker: DummyTicker(ticker)  # type: ignore[assignment]
    try:
        result = compute_peer_multiple(
            "JPM",
            {"book_value_per_share": 50.0, "ebitda": 200.0, "earnings_per_share": 5.0},
            test_db,
        )
    finally:
        yfinance.Ticker = original_ticker  # type: ignore[assignment]

    assert result["metric_used"] == "P/B"
    assert result["median_multiple"] > 0
    assert result["implied_value"] > 0