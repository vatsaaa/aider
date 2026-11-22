"""AV1 Data Agent

This agent pulls the latest annual financials from the SEC XBRL companyfacts
API, downloads recent 10-K/10-Q filings to scan for auditor flags, gathers
market and peer data, persists a `DataPackage`, and publishes an
`M5DataOutput` downstream. Missing SEC financials are a `FatalError` so the run
goes to the DLQ instead of AV2 modelling on default assumptions.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from sqlalchemy import text

from core.agent_base import BaseAgent
from core.bus import Message
from core.exceptions import FatalError
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

        user_agent = str(getattr(self.settings, "SEC_USER_AGENT", "") or "")
        warnings: List[str] = []

        try:
            sec = edgar.fetch_company_financials(ticker, user_agent=user_agent)
        except edgar.EdgarError as exc:
            self.log("av1_sec_financials_unavailable", level="error", run_id=message.pipeline_run_id, ticker=ticker, error=str(exc))
            raise FatalError("sec_financials_unavailable", run_id=message.pipeline_run_id) from exc

        filing_paths: List[str] = []
        try:
            filing_paths = edgar.fetch_filings(ticker, user_agent=user_agent)
        except edgar.EdgarError as exc:
            warnings.append(f"filing_download_failed: {exc}")
            self.log("av1_filing_download_failed", level="warning", run_id=message.pipeline_run_id, ticker=ticker, error=str(exc))

        filings_parsed: List[Dict[str, Any]] = []
        filing_texts: List[str] = []
        for p in filing_paths:
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as fh:
                    filing_texts.append(fh.read())
            except OSError as exc:
                warnings.append(f"filing_read_failed: {p}: {exc}")
                continue
            if p.lower().endswith(".xml"):
                try:
                    filings_parsed.append(edgar.parse_xbrl_file(p))
                except Exception as exc:
                    warnings.append(f"filing_parse_failed: {p}: {exc}")
        if not filing_texts:
            warnings.append("no_filing_text_scanned_for_auditor_flags")

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
        except Exception as exc:
            market = {}
            warnings.append(f"market_data_failed: {exc}")

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
            "cik": sec.get("cik"),
            "entity_name": sec.get("entity_name"),
            "financials": sec["financials"],
            "opening_balance_sheet": sec["opening_balance_sheet"],
            "filings": filings_parsed,
            "market": market,
            "peers": peer_data,
            "auditor_flags": flags,
            "data_quality": {
                "source": "sec_companyfacts",
                "fiscal_year_end": sec["financials"].get("fiscal_year_end"),
                "missing_fields": sec.get("missing_fields", []),
                "warnings": warnings,
            },
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
