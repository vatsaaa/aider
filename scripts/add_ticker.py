"""Add a single ticker to the coverage universe.

This CLI is intentionally small and idempotent. It inserts the coverage row if
it does not already exist and leaves existing rows untouched.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from sqlalchemy import create_engine, text


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments for the add-ticker CLI."""

    parser = argparse.ArgumentParser(description="Add one ticker to coverage_universe")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--sector", required=True)
    parser.add_argument("--peers", required=True, help="Comma-separated peer tickers")
    parser.add_argument("--price-trigger", required=True, type=float)
    return parser.parse_args(list(argv) if argv is not None else None)


def add_ticker(database_url: str, ticker: str, sector: str, peers: list[str], price_trigger_pct: float) -> bool:
    """Insert a single ticker into the coverage universe if it does not already exist."""

    engine = create_engine(database_url, future=True)
    with engine.begin() as connection:
        existing = connection.execute(
            text("SELECT 1 FROM coverage_universe WHERE ticker = :ticker"),
            {"ticker": ticker},
        ).first()
        if existing:
            print(f"Ticker {ticker} already exists; skipping.")
            return False

        notes = {
            "sector": sector,
            "peers": peers,
            "price_trigger_pct": price_trigger_pct,
        }
        connection.execute(
            text(
                "INSERT INTO coverage_universe (ticker, added_at, notes) "
                "VALUES (:ticker, CURRENT_TIMESTAMP, :notes)"
            ),
            {"ticker": ticker, "notes": json.dumps(notes, sort_keys=True)},
        )
    print(f"Inserted {ticker} into coverage_universe.")
    return True


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point for adding one ticker."""

    args = parse_args(argv)
    from core.config import settings

    peers = [peer.strip() for peer in args.peers.split(",") if peer.strip()]
    add_ticker(settings.AIDER_DATABASE_URL, args.ticker.upper(), args.sector, peers, args.price_trigger)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
