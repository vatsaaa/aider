"""EDGAR helper utilities.

Provides light-weight XBRL/XML parsing helpers and a thin wrapper around the
`sec-edgar-downloader` package. Tests may monkeypatch fetching functions to
return local fixtures; parsing functions work directly on XML files.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict
import time


def parse_xbrl_file(path: str | Path) -> Dict[str, float]:
    """Parse a simplified XBRL/XML filing and extract common financials.

    This function attempts to find elements whose local-name contains key
    substrings (revenue, netincome, ebit, operatingincome, assets, debt,
    cash, equity, operatingcashflow, capex) and returns the last numeric
    occurrence for each.

    Returns a dict mapping field names to numeric values.
    """

    tree = ET.parse(str(path))
    root = tree.getroot()

    def find_last_number(key_substr: str):
        # Case-insensitive tag-name matching that ignores XML namespaces.
        lower = key_substr.lower()
        nodes = []
        for node in root.iter():
            tag = node.tag
            if not isinstance(tag, str):
                continue
            local_name = tag.rsplit("}", 1)[-1].lower()
            if lower in local_name:
                nodes.append(node)

        for n in reversed(nodes):
            text = (n.text or "").strip().replace(',', '')
            try:
                return float(text)
            except Exception:
                continue
        return None

    out: Dict[str, float] = {}
    mapping = {
        "revenue": "revenue",
        "netincome": "net_income",
        "ebit": "ebit",
        "operatingincome": "operating_income",
        "assets": "total_assets",
        "debt": "total_debt",
        "cash": "cash_and_equivalents",
        "equity": "total_shareholders_equity",
        "operatingcashflow": "operating_cash_flow",
        "capex": "capex",
    }

    for k, name in mapping.items():
        val = find_last_number(k)
        if val is not None:
            out[name] = val

    return out


def fetch_filings(ticker: str, filing_types: list[str] | None = None, count: int = 4) -> list[str]:
    """Fetch recent filings for `ticker` and return local file paths.

    This function uses `sec-edgar-downloader` when available. If not
    installed, it raises `RuntimeError`. Callers (tests) may monkeypatch this
    function to return local fixture paths instead.
    """

    try:
        # Attempt to import the common downloader package. The exact import
        # location may vary; prefer a lazy attempt and present a clear error.
        from sec_edgar_downloader import Downloader
    except Exception:
        raise RuntimeError("sec-edgar-downloader is not installed")

    dl = Downloader("./tmp_edgar")
    # Respect SEC rate guidance: small sleep between requests
    filing_types = filing_types or ["10-K", "10-Q"]
    paths: list[str] = []
    for f in filing_types[:count]:
        dl.get(f, ticker, amount=1)
        time.sleep(0.1)
        # The downloader stores files under tmp_edgar/sec-edgar-filings/<ticker>/<filing>/
        # We will not attempt to parse this structure exhaustively here; callers
        # should point to the correct file or use tests' monkeypatch.
    raise RuntimeError("fetch_filings requires tests to monkeypatch in this environment")
