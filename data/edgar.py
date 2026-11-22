"""EDGAR helper utilities.

Provides the SEC data access used by AV1:

- `fetch_company_financials` reads the SEC XBRL "companyfacts" API and maps the
  latest annual 10-K figures onto the inputs AV2/AV3 consume.
- `fetch_filings` downloads the latest raw filings with `sec-edgar-downloader`
  so their text can be scanned for auditor flags.
- `parse_xbrl_file` extracts common financials from simplified XBRL/XML files.
"""

from __future__ import annotations

import threading
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import requests

SEC_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
DEFAULT_DOWNLOAD_FOLDER = Path("tmp_edgar")
_ANNUAL_FORMS = ("10-K", "10-K/A", "20-F", "40-F")
_REQUEST_TIMEOUT_SECONDS = 20

_ticker_map_lock = threading.Lock()
_ticker_map_cache: Dict[str, int] = {}


class EdgarError(RuntimeError):
    """Raised when SEC EDGAR data cannot be fetched or lacks required fields."""


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


def _sec_session(user_agent: str, session: Optional[requests.Session] = None) -> requests.Session:
    """Return a requests session carrying the SEC-mandated User-Agent header."""

    if not user_agent or not user_agent.strip():
        raise EdgarError("SEC_USER_AGENT is not configured")
    sess = session or requests.Session()
    sess.headers.update({"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"})
    return sess


def _get_json(sess: requests.Session, url: str) -> Any:
    """GET a JSON document from SEC, wrapping transport errors in `EdgarError`."""

    try:
        response = sess.get(url, timeout=_REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        return response.json()
    except EdgarError:
        raise
    except Exception as exc:
        raise EdgarError(f"SEC request failed for {url}: {exc}") from exc


def lookup_cik(ticker: str, user_agent: str, session: Optional[requests.Session] = None) -> int:
    """Resolve a ticker symbol to its SEC CIK using the SEC ticker map."""

    symbol = ticker.strip().upper()
    with _ticker_map_lock:
        if symbol in _ticker_map_cache:
            return _ticker_map_cache[symbol]
    data = _get_json(_sec_session(user_agent, session), SEC_TICKER_MAP_URL)
    rows = data.values() if isinstance(data, dict) else data
    mapping = {str(row["ticker"]).upper(): int(row["cik_str"]) for row in rows if isinstance(row, dict) and "ticker" in row and "cik_str" in row}
    with _ticker_map_lock:
        _ticker_map_cache.update(mapping)
    if symbol not in mapping:
        raise EdgarError(f"Ticker {symbol} not found in SEC ticker map")
    return mapping[symbol]


def _days_between(start: str, end: str) -> int:
    """Return the number of days between two ISO dates."""

    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def _annual_entries(facts: Dict[str, Any], tags: Iterable[str], unit: str, duration: bool, taxonomy: str = "us-gaap") -> list[dict[str, Any]]:
    """Return annual-report entries across `tags`, one per period end, newest first.

    Companies switch XBRL tags over time (e.g. `Revenues` →
    `RevenueFromContractWithCustomerExcludingAssessedTax`), so every tag is
    searched. For a given period the latest filing wins (restatements), then
    the earlier tag in `tags`. Duration facts (income/cash-flow items) must
    span roughly one fiscal year; instant facts (balance-sheet items) only
    need an `end` date.
    """

    tax = (facts.get("facts") or {}).get(taxonomy) or {}
    candidates: list[tuple[str, str, int, dict[str, Any]]] = []
    for priority, tag in enumerate(tags):
        units = ((tax.get(tag) or {}).get("units") or {}).get(unit) or []
        for entry in units:
            if entry.get("form") not in _ANNUAL_FORMS or entry.get("val") is None or not entry.get("end"):
                continue
            if duration:
                if not entry.get("start") or not 350 <= _days_between(entry["start"], entry["end"]) <= 380:
                    continue
            candidates.append((entry["end"], entry.get("filed", ""), -priority, entry))
    candidates.sort(key=lambda item: item[:3], reverse=True)
    by_end: dict[str, dict[str, Any]] = {}
    for end, _, _, entry in candidates:
        by_end.setdefault(end, entry)
    return list(by_end.values())


def _latest(
    facts: Dict[str, Any],
    tags: Iterable[str],
    duration: bool,
    as_of: Optional[str] = None,
    unit: str = "USD",
    taxonomy: str = "us-gaap",
) -> Optional[float]:
    """Return the annual value for the period ending `as_of`, or the most recent one when `as_of` is None.

    Pinning to `as_of` keeps every figure on the same fiscal year, so stale
    values from a discontinued tag are treated as missing rather than mixed in.
    """

    for entry in _annual_entries(facts, tags, unit, duration, taxonomy):
        if as_of is None or entry["end"] == as_of:
            return float(entry["val"])
    return None


def _ratio(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    """Return numerator / denominator, or None when either is missing or the denominator is not positive."""

    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


REVENUE_TAGS = ("Revenues", "RevenuesNetOfInterestExpense", "RevenueFromContractWithCustomerExcludingAssessedTax", "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet")
COST_OF_REVENUE_TAGS = ("CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold", "CostOfServices")
OPERATING_INCOME_TAGS = ("OperatingIncomeLoss",)
NET_INCOME_TAGS = ("NetIncomeLoss", "ProfitLoss")
DA_TAGS = ("DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet", "DepreciationAndAmortization", "Depreciation")
TAX_TAGS = ("IncomeTaxExpenseBenefit",)
PRETAX_TAGS = ("IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest", "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments")
INTEREST_TAGS = ("InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt", "InterestAndDebtExpense")
OCF_TAGS = ("NetCashProvidedByUsedInOperatingActivities",)
CAPEX_TAGS = ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets")
DIVIDEND_TAGS = ("PaymentsOfDividendsCommonStock", "PaymentsOfDividends")
ASSETS_TAGS = ("Assets",)
LIABILITIES_TAGS = ("Liabilities",)
LIABILITIES_AND_EQUITY_TAGS = ("LiabilitiesAndStockholdersEquity",)
EQUITY_TAGS = ("StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "StockholdersEquity")
CURRENT_ASSETS_TAGS = ("AssetsCurrent",)
CURRENT_LIABILITIES_TAGS = ("LiabilitiesCurrent",)
PPE_TAGS = ("PropertyPlantAndEquipmentNet", "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization")
CASH_TAGS = ("CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents")
LONG_TERM_DEBT_NONCURRENT_TAGS = ("LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations")
CURRENT_MATURITIES_TAGS = ("LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent")
TOTAL_CURRENT_DEBT_TAGS = ("DebtCurrent",)
TOTAL_LONG_TERM_DEBT_TAGS = ("LongTermDebt", "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities")
SHORT_TERM_BORROWING_TAGS = (("CommercialPaper",), ("ShortTermBorrowings",), ("OtherShortTermBorrowings",))


def _debt_at(company_facts: Dict[str, Any], fy_end: str) -> tuple[Optional[float], Optional[float]]:
    """Return `(total_debt, current_debt)` at `fy_end`, avoiding double counting across overlapping tags.

    `DebtCurrent` already includes short-term borrowings, and `LongTermDebt`
    already includes current maturities, so those totals are only combined
    with components they do not contain. When no long-term debt tag is
    reported (e.g. the filer uses a custom tag), total debt is `None` rather
    than understated as current borrowings only.
    """

    def value(tags: Iterable[str]) -> Optional[float]:
        return _latest(company_facts, tags, duration=False, as_of=fy_end)

    short_term_parts = [v for v in (value(tags) for tags in SHORT_TERM_BORROWING_TAGS) if v is not None]
    short_term = sum(short_term_parts) if short_term_parts else None
    current_maturities = value(CURRENT_MATURITIES_TAGS)
    total_current = value(TOTAL_CURRENT_DEBT_TAGS)
    if total_current is not None:
        current: Optional[float] = total_current
    elif current_maturities is not None or short_term is not None:
        current = (current_maturities or 0.0) + (short_term or 0.0)
    else:
        current = None

    noncurrent = value(LONG_TERM_DEBT_NONCURRENT_TAGS)
    if noncurrent is not None:
        return noncurrent + (current or 0.0), current
    total_long_term = value(TOTAL_LONG_TERM_DEBT_TAGS)
    if total_long_term is not None:
        return total_long_term + (short_term or 0.0), current
    return None, current


def _revenue_share(amount: Optional[float], revenue: float) -> Optional[float]:
    """Express `amount` relative to revenue in the form AV2's `_percent_of_revenue` expects.

    AV2 treats values with magnitude <= 1 as ratios and larger values as dollar
    amounts it divides by revenue, so a ratio above 100% (e.g. current assets
    exceeding revenue) is passed as the dollar amount to avoid being scaled twice.
    """

    if amount is None or revenue <= 0:
        return None
    share = amount / revenue
    return share if abs(share) <= 1.0 else amount


def extract_financials(company_facts: Dict[str, Any]) -> Dict[str, Any]:
    """Map SEC companyfacts JSON onto the `financials` / `opening_balance_sheet` inputs used by AV2 and AV3.

    Values come from the most recent annual report; every figure is pinned to
    the latest fiscal year end found for revenue. Ratios are expressed as a
    fraction of revenue. Liabilities are taken as `LiabilitiesAndStockholdersEquity`
    minus total equity when available, so temporary (mezzanine) equity is
    counted with liabilities and the opening balance sheet ties to the
    reported total. Raises `EdgarError` when revenue, assets, or equity are missing.
    """

    revenue_history = _annual_entries(company_facts, REVENUE_TAGS, "USD", duration=True)
    revenue = float(revenue_history[0]["val"]) if revenue_history else None
    fy_end = revenue_history[0]["end"] if revenue_history else None
    latest_balance_sheet = _annual_entries(company_facts, ASSETS_TAGS, "USD", duration=False)
    if fy_end and latest_balance_sheet and _days_between(fy_end, latest_balance_sheet[0]["end"]) > 31:
        raise EdgarError(
            f"SEC companyfacts revenue is stale: latest revenue fact ends {fy_end} but the latest annual balance sheet is "
            f"{latest_balance_sheet[0]['end']} (revenue likely reported under an unmapped tag)"
        )
    assets = _latest(company_facts, ASSETS_TAGS, duration=False, as_of=fy_end) if fy_end else None
    equity = _latest(company_facts, EQUITY_TAGS, duration=False, as_of=fy_end) if fy_end else None
    missing = [name for name, value in (("revenue", revenue), ("total_assets", assets), ("total_equity", equity)) if value is None]
    if missing:
        raise EdgarError(f"SEC companyfacts missing required fields: {', '.join(missing)}")

    liabilities_and_equity = _latest(company_facts, LIABILITIES_AND_EQUITY_TAGS, duration=False, as_of=fy_end)
    reported_liabilities = _latest(company_facts, LIABILITIES_TAGS, duration=False, as_of=fy_end)
    if liabilities_and_equity is not None:
        liabilities = liabilities_and_equity - equity
    elif reported_liabilities is not None:
        liabilities = reported_liabilities
    else:
        liabilities = assets - equity

    cost_of_revenue = _latest(company_facts, COST_OF_REVENUE_TAGS, duration=True, as_of=fy_end)
    operating_income = _latest(company_facts, OPERATING_INCOME_TAGS, duration=True, as_of=fy_end)
    net_income = _latest(company_facts, NET_INCOME_TAGS, duration=True, as_of=fy_end)
    da = _latest(company_facts, DA_TAGS, duration=True, as_of=fy_end)
    tax = _latest(company_facts, TAX_TAGS, duration=True, as_of=fy_end)
    pretax = _latest(company_facts, PRETAX_TAGS, duration=True, as_of=fy_end)
    interest = _latest(company_facts, INTEREST_TAGS, duration=True, as_of=fy_end)
    ocf = _latest(company_facts, OCF_TAGS, duration=True, as_of=fy_end)
    capex = _latest(company_facts, CAPEX_TAGS, duration=True, as_of=fy_end)
    dividends = _latest(company_facts, DIVIDEND_TAGS, duration=True, as_of=fy_end)
    cash = _latest(company_facts, CASH_TAGS, duration=False, as_of=fy_end)
    current_assets = _latest(company_facts, CURRENT_ASSETS_TAGS, duration=False, as_of=fy_end)
    current_liabilities = _latest(company_facts, CURRENT_LIABILITIES_TAGS, duration=False, as_of=fy_end)
    ppe = _latest(company_facts, PPE_TAGS, duration=False, as_of=fy_end)
    # cover-page share count is dated near the filing date, not the fiscal year end
    shares = _latest(company_facts, ("EntityCommonStockSharesOutstanding",), duration=False, unit="shares", taxonomy="dei")

    # bank revenue is reported after interest expense; AV2 must not deduct interest a second time
    revenue_net_of_interest = any(
        entry["end"] == fy_end and float(entry["val"]) == revenue
        for entry in _annual_entries(company_facts, ("RevenuesNetOfInterestExpense",), "USD", duration=True)
    )

    debt, current_debt = _debt_at(company_facts, fy_end)
    # AV2 models cash and debt separately, so working capital excludes them
    operating_current_assets = current_assets - (cash or 0.0) if current_assets is not None else None
    operating_current_liabilities = current_liabilities - (current_debt or 0.0) if current_liabilities is not None else None

    da_pct = _ratio(da, revenue)
    opex_pct: Optional[float] = None
    if operating_income is not None and cost_of_revenue is not None:
        # AV2 computes EBIT = revenue - COGS - opex - D&A, so back out opex to match reported operating income
        opex_pct = (revenue - cost_of_revenue - operating_income) / revenue - (da_pct or 0.0)

    tax_rate = _ratio(tax, pretax)
    if tax_rate is not None and not 0.0 <= tax_rate <= 0.6:
        tax_rate = None

    financials: Dict[str, Any] = {
        "historical_revenue": revenue,
        "revenue_history": {entry["end"]: float(entry["val"]) for entry in revenue_history[:5]},
        "fiscal_year_end": fy_end,
        "revenue_net_of_interest": revenue_net_of_interest,
        "cogs_pct_revenue": _revenue_share(cost_of_revenue, revenue),
        "opex_pct_revenue": opex_pct,
        "da_pct_revenue": _revenue_share(da, revenue),
        "tax_rate": tax_rate,
        "interest_rate": _ratio(interest, debt),
        "debt": debt,
        "cash": cash,
        "current_assets_pct_revenue": _revenue_share(operating_current_assets, revenue),
        "current_liabilities_pct_revenue": _revenue_share(operating_current_liabilities, revenue),
        "net_ppe_pct_revenue": _revenue_share(ppe, revenue),
        "capex_pct_revenue": _revenue_share(abs(capex) if capex is not None else None, revenue),
        "dividend_payout_pct": _ratio(abs(dividends) if dividends is not None else None, net_income),
        "operating_income": operating_income,
        "net_income": net_income,
        "operating_cash_flow": ocf,
        "equity": equity,
        "shares_outstanding": shares,
    }
    missing_optional = sorted(key for key, value in financials.items() if value is None)
    return {
        "financials": {key: value for key, value in financials.items() if value is not None},
        "opening_balance_sheet": {"assets": assets, "liabilities": liabilities, "equity": equity},
        "missing_fields": missing_optional,
    }


def fetch_company_financials(ticker: str, user_agent: str, session: Optional[requests.Session] = None) -> Dict[str, Any]:
    """Fetch SEC companyfacts for `ticker` and return the extracted financial inputs.

    The result has `financials`, `opening_balance_sheet`, `missing_fields`,
    `cik` and `entity_name` keys. Raises `EdgarError` on transport failures,
    unknown tickers, or missing core fields.
    """

    sess = _sec_session(user_agent, session)
    cik = lookup_cik(ticker, user_agent, sess)
    company_facts = _get_json(sess, SEC_COMPANY_FACTS_URL.format(cik=cik))
    extracted = extract_financials(company_facts)
    extracted["cik"] = cik
    extracted["entity_name"] = company_facts.get("entityName")
    return extracted


def _split_user_agent(user_agent: str) -> tuple[str, str]:
    """Split an SEC User-Agent ("Company Name email@domain") into (company, email)."""

    tokens = (user_agent or "").split()
    emails = [token for token in tokens if "@" in token]
    if not emails:
        raise EdgarError("SEC_USER_AGENT must include a contact email address")
    company = " ".join(token for token in tokens if token != emails[0]) or emails[0]
    return company, emails[0]


def fetch_filings(
    ticker: str,
    filing_types: list[str] | None = None,
    count: int = 4,
    *,
    user_agent: str,
    download_folder: str | Path | None = None,
) -> list[str]:
    """Download the latest filing of each type for `ticker` and return the local file paths.

    Uses `sec-edgar-downloader` (v5 layout:
    `<folder>/sec-edgar-filings/<TICKER>/<FORM>/<ACCESSION>/full-submission.txt`).
    At most `count` filing types are fetched. Raises `EdgarError` on failure.
    """

    try:
        from sec_edgar_downloader import Downloader
    except ImportError as exc:
        raise EdgarError("sec-edgar-downloader is not installed") from exc

    company, email = _split_user_agent(user_agent)
    folder = Path(download_folder) if download_folder is not None else DEFAULT_DOWNLOAD_FOLDER
    downloader = Downloader(company, email, folder)
    symbol = ticker.strip().upper()
    paths: list[str] = []
    for form in (filing_types or ["10-K", "10-Q"])[:count]:
        try:
            downloader.get(form, symbol, limit=1, download_details=False)
        except Exception as exc:
            raise EdgarError(f"Failed to download {form} for {symbol}: {exc}") from exc
        candidates = sorted(
            (folder / "sec-edgar-filings" / symbol / form).glob("*/full-submission.txt"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            paths.append(str(candidates[0]))
    return paths
