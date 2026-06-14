"""Data access layer for external data sources.

This package contains modules for fetching and parsing data from external
sources like SEC EDGAR, FRED, and yfinance.
"""

from .edgar import parse_xbrl_file, fetch_filings

__all__ = ["parse_xbrl_file", "fetch_filings"]
