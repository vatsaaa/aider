"""AV1 Data Agent

This agent fetches 10-K/10-Q filings, parses financials, gathers market and
peer data, scans for auditor flags, persists a `DataPackage`, and publishes
an `M5DataOutput` downstream.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from sqlalchemy import text

from core.agent_base import BaseAgent
from core.bus import Message
from core.schemas import M4ScreenOutput, M5DataOutput
from data import edgar
from core import auditor_flags
from db.idempotent_writes import upsert_data_package


class AV1DataAgent(BaseAgent):
    """Agent that produces `M5DataOutput` by gathering filings and market data."""

    stream_in = "stage:rs3:output"
    stream_out = "stage:av1:output"
    group_name = "av1-group"
    agent_name = "av1_data"

    def process(self, message: Message) -> M5DataOutput:
        """Process an incoming `M4ScreenOutput` and produce `M5DataOutput`.

        The method operates on the first candidate in `m4.candidates`.
        """

        m4 = M4ScreenOutput.model_validate(message.payload)
        if not m4.candidates:
            raise ValueError("no candidates provided")

        ticker = m4.candidates[0].ticker

        # Fetch filings (tests may monkeypatch edgar.fetch_filings)
        filing_paths = []
        try:
            filing_paths = edgar.fetch_filings(ticker)
        except Exception:
            # Tests will typically monkeypatch fetch_filings; on failure continue
            filing_paths = []

        filings_parsed: List[Dict[str, Any]] = []
        filing_texts: List[str] = []
        for p in filing_paths:
            try:
                parsed = edgar.parse_xbrl_file(p)
                filings_parsed.append(parsed)
                try:
                    with open(p, "r", encoding="utf-8") as fh:
                        filing_texts.append(fh.read())
                except Exception:
                    filing_texts.append("")
            except Exception:
                continue

        # Market data via yfinance (tests monkeypatch)
        market: Dict[str, Any] = {}
        try:
            import yfinance as yf

            t = yf.Ticker(ticker)
            info = getattr(t, "info", {}) or {}
            market = {
                "shares_outstanding": info.get("sharesOutstanding"),
                "market_cap": info.get("marketCap"),
                "beta": info.get("beta"),
            }
        except Exception:
            market = {}

        # Peer data: attempt to infer primary sector from the incoming message
        primary_sector = None
        # message.payload is the validated M4 payload; original envelope may carry
        # previous stage fields under message.data or message.data['payload']
        try:
            primary_sector = message.data.get("primary_sector") or (message.data.get("payload") or {}).get("primary_sector")
        except Exception:
            primary_sector = None

        peers: List[str] = []
        if primary_sector:
            peers = self.repository.coverage_tickers_for_sector(primary_sector)

        peer_data: Dict[str, Any] = {}
        try:
            import yfinance as yf
            for p in peers:
                try:
                    pt = yf.Ticker(p)
                    peer_data[p] = getattr(pt, "info", {}) or {}
                except Exception:
                    continue
        except Exception:
            peer_data = {}

        # Auditor flags scan
        flags = auditor_flags.scan_texts_for_flags(filing_texts)

        # Persist DataPackage
        package = {
            "ticker": ticker,
            "filings": filings_parsed,
            "market": market,
            "peers": peer_data,
            "auditor_flags": flags,
        }

        data_package_id = self.repository.save_data_package(
            run_id=message.pipeline_run_id,
            ticker=ticker,
            payload=package,
            auditor_flags=flags,
        )

        # Build and return M5DataOutput
        m5 = M5DataOutput(ticker=ticker, data_package_id=data_package_id, auditor_flags=flags)
        return m5


__all__ = ["AV1DataAgent"]
