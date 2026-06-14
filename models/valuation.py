"""Valuation helpers for AV3.

This module computes discounted cash flow value, resolves peer multiples from
the coverage universe, and provides small deterministic helpers used by the
valuation agent and its tests.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping

from sqlalchemy import text


VALUATION_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "valuation.yaml"
SECTORS_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "sectors.yaml"

_DEFAULT_WACCS = [0.09, 0.10, 0.11, 0.12]
_DEFAULT_GROWTH_RATES = [0.02, 0.025, 0.03, 0.035]

_SECTOR_ALIASES = {
    "banking": "Financials",
    "banks": "Financials",
    "financials": "Financials",
    "technology": "Information Technology",
    "it": "Information Technology",
    "information technology": "Information Technology",
    "consumer discretionary": "Consumer Discretionary",
    "retail/consumer": "Consumer Discretionary",
    "consumer staples": "Consumer Staples",
    "healthcare": "Healthcare",
    "industrials": "Industrials",
    "energy": "Energy",
    "reit": "Real Estate",
    "real estate": "Real Estate",
}

_MULTIPLE_TO_YFINANCE_KEY = {
    "EV/EBITDA": "enterpriseToEbitda",
    "EV/REVENUE": "enterpriseToRevenue",
    "PE": "forwardPE",
    "P/E": "forwardPE",
    "P/B": "priceToBook",
}

_MULTIPLE_TO_SUBJECT_METRIC = {
    "EV/EBITDA": "ebitda",
    "EV/REVENUE": "revenue",
    "PE": "earnings_per_share",
    "P/E": "earnings_per_share",
    "P/B": "book_value_per_share",
}


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file into a dictionary, returning an empty mapping when missing."""

    if not path.exists():
        return {}
    try:
        import yaml
    except Exception:
        return {}
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    return loaded if isinstance(loaded, dict) else {}


@lru_cache(maxsize=1)
def _valuation_config() -> dict[str, Any]:
    """Return the valuation config loaded from disk."""

    return _load_yaml(VALUATION_CONFIG_PATH)


@lru_cache(maxsize=1)
def _sector_definitions() -> dict[str, dict[str, Any]]:
    """Return sector definitions keyed by normalized sector name."""

    try:
        import yaml
    except Exception:
        return {}

    if not SECTORS_CONFIG_PATH.exists():
        return {}

    with SECTORS_CONFIG_PATH.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or []

    definitions: dict[str, dict[str, Any]] = {}
    if isinstance(loaded, list):
        for entry in loaded:
            if isinstance(entry, dict) and entry.get("name"):
                definitions[_normalize_sector_name(str(entry["name"]))] = entry
    elif isinstance(loaded, dict):
        for key, value in loaded.items():
            if isinstance(value, dict):
                definitions[_normalize_sector_name(str(key))] = value
    return definitions


def _normalize_sector_name(sector: str) -> str:
    """Normalize a sector label so aliases and config names line up."""

    return _SECTOR_ALIASES.get(sector.strip().lower(), sector.strip())


def _yfinance_multiple_key(primary_multiple: str) -> str:
    """Map a sector primary multiple to the corresponding yfinance info key."""

    normalized = primary_multiple.strip().upper()
    return _MULTIPLE_TO_YFINANCE_KEY.get(normalized, "enterpriseToEbitda")


def _subject_metric_name(primary_multiple: str) -> str:
    """Map a sector primary multiple to the subject-company metric name."""

    normalized = primary_multiple.strip().upper()
    return _MULTIPLE_TO_SUBJECT_METRIC.get(normalized, "ebitda")


def _as_float(value: Any, default: float = 0.0) -> float:
    """Convert a value to float while tolerating empty inputs."""

    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _json_loads_if_needed(value: Any) -> Any:
    """Decode JSON strings returned from the database when needed."""

    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def compute_dcf(fcf_stream: Iterable[float], wacc: float, terminal_growth: float | None = None) -> dict[str, Any]:
    """Compute DCF enterprise value for a five-year FCF stream."""

    growth = terminal_growth if terminal_growth is not None else _as_float(_valuation_config().get("terminal_growth"), 0.025)
    fcf_values = [float(value) for value in fcf_stream]
    if len(fcf_values) != 5:
        raise ValueError("fcf_stream must contain exactly 5 yearly values")
    if wacc <= growth:
        raise ValueError("wacc must be greater than terminal growth")

    explicit_pv = [fcf_values[idx] / ((1.0 + wacc) ** (idx + 1)) for idx in range(5)]
    terminal_value = fcf_values[-1] * (1.0 + growth) / (wacc - growth)
    terminal_pv = terminal_value / ((1.0 + wacc) ** 5)
    enterprise_value = sum(explicit_pv) + terminal_pv

    return {
        "enterprise_value": enterprise_value,
        "terminal_value": terminal_value,
        "terminal_present_value": terminal_pv,
        "explicit_fcf_present_value": sum(explicit_pv),
        "terminal_value_share": terminal_pv / enterprise_value if enterprise_value else 0.0,
        "terminal_growth": growth,
        "wacc": wacc,
        "fcf_stream": fcf_values,
        "present_values": explicit_pv,
    }


def build_sensitivity_table(
    fcf_stream: Iterable[float],
    *,
    wacc_values: Iterable[float] | None = None,
    growth_rates: Iterable[float] | None = None,
) -> dict[str, dict[str, float]]:
    """Build a 4x4 DCF sensitivity table keyed by WACC row and growth column."""

    wacc_list = list(wacc_values or _DEFAULT_WACCS)
    growth_list = list(growth_rates or _DEFAULT_GROWTH_RATES)
    table: dict[str, dict[str, float]] = {}
    for wacc in wacc_list:
        row_key = f"{wacc:.1%}"
        table[row_key] = {}
        for growth in growth_list:
            result = compute_dcf(fcf_stream, wacc, terminal_growth=growth)
            table[row_key][f"{growth:.1%}"] = float(result["enterprise_value"])
    return table


def derive_rating(current_price: float, target_price: float, hurdle_rate: float = 0.15) -> str:
    """Convert target upside/downside into a BUY/HOLD/SELL rating."""

    if current_price <= 0:
        raise ValueError("current_price must be positive")
    expected_return = (target_price - current_price) / current_price
    if expected_return > hurdle_rate:
        return "BUY"
    if expected_return < -hurdle_rate:
        return "SELL"
    return "HOLD"


def _coverage_rows(db: Any) -> list[tuple[str, Any]]:
    """Return ticker and notes rows from the coverage universe."""

    with db.begin() as conn:
        rows = conn.execute(text("SELECT ticker, notes FROM coverage_universe")).fetchall()
    return [(str(row[0]), row[1]) for row in rows]


def _row_notes(notes: Any) -> dict[str, Any]:
    """Parse a coverage row notes field into a dictionary when possible."""

    loaded = _json_loads_if_needed(notes)
    if isinstance(loaded, dict):
        return loaded
    if isinstance(loaded, str) and loaded:
        return {"sector": loaded}
    return {}


def _sector_from_notes(notes: Any) -> str | None:
    """Extract a sector label from a coverage-universe notes payload."""

    parsed = _row_notes(notes)
    sector = parsed.get("sector") or parsed.get("primary_sector") or parsed.get("industry")
    if sector:
        return str(sector)
    return None


def _peers_for_ticker(ticker: str, db: Any) -> tuple[str | None, list[str]]:
    """Resolve a ticker's sector and peer list from the coverage universe."""

    rows = _coverage_rows(db)
    subject_sector: str | None = None
    subject_notes: dict[str, Any] = {}
    for row_ticker, notes in rows:
        if row_ticker == ticker:
            subject_notes = _row_notes(notes)
            subject_sector = _sector_from_notes(notes)
            break

    peers = subject_notes.get("peers")
    if isinstance(peers, str):
        peers = [part.strip() for part in peers.split(",") if part.strip()]
    if isinstance(peers, list) and peers:
        return subject_sector, [str(peer) for peer in peers if str(peer) != ticker]

    if subject_sector:
        normalized = _normalize_sector_name(subject_sector)
        inferred: list[str] = []
        for row_ticker, notes in rows:
            if row_ticker == ticker:
                continue
            row_sector = _sector_from_notes(notes)
            if row_sector and _normalize_sector_name(row_sector) == normalized:
                inferred.append(row_ticker)
        return subject_sector, inferred

    return subject_sector, [row_ticker for row_ticker, _ in rows if row_ticker != ticker]


def _peer_multiple_value(info: Mapping[str, Any], multiple: str) -> float | None:
    """Extract the relevant multiple from a yfinance info dict."""

    key = _yfinance_multiple_key(multiple)
    candidates = [
        info.get(key),
        info.get(key.lower()),
        info.get(multiple),
        info.get(multiple.lower()),
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            numeric = float(candidate)
        except (TypeError, ValueError):
            continue
        if numeric > 0:
            return numeric
    return None


def compute_peer_multiple(ticker: str, subject_metrics: Mapping[str, float], db: Any, settings: Any | None = None) -> dict[str, Any]:
    """Compute a sector-appropriate peer multiple from coverage-universe peers."""

    sector_label, peers = _peers_for_ticker(ticker, db)
    sector_key = _normalize_sector_name(sector_label or "") if sector_label else None
    sector_defs = _sector_definitions()

    sector_entry: dict[str, Any] | None = None
    if sector_key and sector_key in sector_defs:
        sector_entry = sector_defs[sector_key]
    elif sector_key:
        for key, value in sector_defs.items():
            if key.lower() == sector_key.lower():
                sector_entry = value
                break
    if sector_entry is None:
        sector_entry = {"name": sector_label or "Unknown", "primary_multiple": "EV/EBITDA", "metrics": []}

    primary_multiple = str(sector_entry.get("primary_multiple", "EV/EBITDA"))
    subject_metric_name = _subject_metric_name(primary_multiple)
    subject_metric = _as_float(subject_metrics.get(subject_metric_name), 0.0)
    if subject_metric <= 0:
        fallback_names = ["ebitda", "book_value_per_share", "book_value", "earnings_per_share", "earnings", "revenue"]
        for fallback_name in fallback_names:
            subject_metric = _as_float(subject_metrics.get(fallback_name), 0.0)
            if subject_metric > 0:
                subject_metric_name = fallback_name
                break
    if subject_metric <= 0:
        raise ValueError(f"missing subject metric for {primary_multiple}: {subject_metric_name}")

    peer_multiples: dict[str, float] = {}
    try:
        import yfinance as yf
    except Exception as exc:
        raise RuntimeError("yfinance is required for peer multiple calculations") from exc

    for peer in peers:
        try:
            info = getattr(yf.Ticker(peer), "info", {}) or {}
        except Exception:
            continue
        multiple_value = _peer_multiple_value(info, primary_multiple)
        if multiple_value is not None:
            peer_multiples[peer] = multiple_value

    if not peer_multiples:
        raise ValueError(f"no peer multiples available for {ticker}")

    median_multiple = median(peer_multiples.values())
    implied_value = median_multiple * subject_metric

    return {
        "ticker": ticker,
        "sector": sector_label or sector_entry.get("name"),
        "metric_used": primary_multiple,
        "subject_metric_name": subject_metric_name,
        "subject_metric": subject_metric,
        "peer_multiples": peer_multiples,
        "median_multiple": float(median_multiple),
        "implied_value": float(implied_value),
        "peers": peers,
    }


__all__ = [
    "compute_dcf",
    "compute_peer_multiple",
    "build_sensitivity_table",
    "derive_rating",
]