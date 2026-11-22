"""Seed the coverage universe and initial price snapshots.

This script reads `config/coverage_universe.yaml`, inserts the ticker coverage
rows idempotently, and stores a starting price snapshot for each ticker so the
rest of the pipeline has a durable baseline.
"""

from __future__ import annotations

import sys
import json
from pathlib import Path
from typing import Any

import yaml
import yfinance as yf
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
COVERAGE_FILE = ROOT / "config" / "coverage_universe.yaml"


def load_coverage_universe(path: Path = COVERAGE_FILE) -> list[dict[str, Any]]:
    """Load the coverage universe definitions from YAML."""

    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or []
    if not isinstance(data, list):
        raise ValueError("coverage_universe.yaml must contain a list of entries")
    return [entry for entry in data if isinstance(entry, dict)]


def get_price(ticker: str) -> float:
    """Fetch a current price for `ticker` from yfinance."""

    try:
        ticker_obj = yf.Ticker(ticker)
        info = getattr(ticker_obj, "fast_info", None)
        if info is not None:
            last_price = getattr(info, "last_price", None)
            if last_price:
                return float(last_price)
        data = ticker_obj.history(period="1d", interval="1d")
        if not data.empty:
            return float(data["Close"].iloc[-1])
    except Exception:
        pass
    return 0.0


def seed_database(database_url: str, coverage_rows: list[dict[str, Any]]) -> None:
    """Insert coverage rows and initial price snapshots into the database."""

    engine = create_engine(database_url, future=True)
    with engine.begin() as connection:
        for index, row in enumerate(coverage_rows, start=1):
            ticker = str(row["ticker"]).upper()
            sector = str(row["sector"])
            peers = row.get("peers", [])
            price_trigger_pct = float(row.get("price_trigger_pct", 0.0))
            print(f"[{index}/{len(coverage_rows)}] seeding {ticker}")
            connection.execute(
                text(
                    "INSERT INTO coverage_universe (ticker, added_at, notes) "
                    "VALUES (:ticker, CURRENT_TIMESTAMP, :notes) "
                    "ON CONFLICT (ticker) DO NOTHING"
                ),
                {
                    "ticker": ticker,
                    "notes": json.dumps(
                        {"sector": sector, "peers": peers, "price_trigger_pct": price_trigger_pct},
                        sort_keys=True,
                    ),
                },
            )
            price = get_price(ticker)
            existing_snapshot = connection.execute(
                text("SELECT 1 FROM price_snapshots WHERE ticker = :ticker LIMIT 1"),
                {"ticker": ticker},
            ).first()
            if existing_snapshot:
                continue
            connection.execute(
                text(
                    "INSERT INTO price_snapshots (ticker, price, snapped_at, source) "
                    "VALUES (:ticker, :price, CURRENT_TIMESTAMP, :source)"
                ),
                {"ticker": ticker, "price": price, "source": "yfinance"},
            )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for seeding the database."""

    _ = argv or sys.argv[1:]
    from core.config import settings

    coverage_rows = load_coverage_universe()
    seed_database(settings.AIDER_DATABASE_URL, coverage_rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
