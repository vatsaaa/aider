"""Data access layer for external data sources.

This package contains modules for fetching and parsing data from external
sources like SEC EDGAR, FRED, and yfinance.
"""

from .edgar import EdgarError, extract_financials, fetch_company_financials, fetch_filings, parse_xbrl_file

__all__ = ["EdgarError", "extract_financials", "fetch_company_financials", "fetch_filings", "parse_xbrl_file"]
