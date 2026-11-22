"""Tests for SEC companyfacts extraction and the sec-edgar-downloader wrapper."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest

from data import edgar
from models.financial_model import ThreeStatementModel


def _duration(val: float, fy: int, form: str = "10-K", filed: str | None = None) -> dict[str, Any]:
    """Build a one-year duration fact entry ending on Sept 30 of `fy`."""

    return {"start": f"{fy - 1}-10-01", "end": f"{fy}-09-30", "val": val, "fy": fy, "fp": "FY", "form": form, "filed": filed or f"{fy}-11-01"}


def _instant(val: float, fy: int, form: str = "10-K") -> dict[str, Any]:
    """Build an instant (balance-sheet) fact entry at Sept 30 of `fy`."""

    return {"end": f"{fy}-09-30", "val": val, "fy": fy, "fp": "FY", "form": form, "filed": f"{fy}-11-01"}


def _usd(*entries: dict[str, Any]) -> dict[str, Any]:
    """Wrap fact entries in the companyfacts USD unit structure."""

    return {"units": {"USD": list(entries)}}


def sample_company_facts() -> dict[str, Any]:
    """Return a small but realistic companyfacts document."""

    quarterly_revenue = {"start": "2024-07-01", "end": "2024-09-30", "val": 95e9, "fy": 2024, "fp": "Q4", "form": "10-Q", "filed": "2024-11-01"}
    return {
        "cik": 320193,
        "entityName": "Example Corp",
        "facts": {
            "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [_instant(15e9, 2024)]}}},
            "us-gaap": {
                "RevenueFromContractWithCustomerExcludingAssessedTax": _usd(
                    _duration(380e9, 2023),
                    _duration(390e9, 2024, filed="2024-11-01"),
                    _duration(391e9, 2024, form="10-K/A", filed="2025-01-15"),
                    quarterly_revenue,
                ),
                "CostOfGoodsAndServicesSold": _usd(_duration(210e9, 2024)),
                "OperatingIncomeLoss": _usd(_duration(120e9, 2024)),
                "NetIncomeLoss": _usd(_duration(95e9, 2024)),
                "DepreciationDepletionAndAmortization": _usd(_duration(11e9, 2024)),
                "IncomeTaxExpenseBenefit": _usd(_duration(25e9, 2024)),
                "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": _usd(_duration(120e9, 2024)),
                "InterestExpense": _usd(_duration(4e9, 2024)),
                "NetCashProvidedByUsedInOperatingActivities": _usd(_duration(115e9, 2024)),
                "PaymentsToAcquirePropertyPlantAndEquipment": _usd(_duration(9e9, 2024)),
                "PaymentsOfDividends": _usd(_duration(15e9, 2024)),
                "Assets": _usd(_instant(350e9, 2023), _instant(365e9, 2024)),
                "Liabilities": _usd(_instant(305e9, 2024)),
                "LiabilitiesAndStockholdersEquity": _usd(_instant(365e9, 2024)),
                "StockholdersEquity": _usd(_instant(57e9, 2024)),
                "AssetsCurrent": _usd(_instant(150e9, 2024)),
                "LiabilitiesCurrent": _usd(_instant(175e9, 2024)),
                "PropertyPlantAndEquipmentNet": _usd(_instant(45e9, 2024)),
                "CashAndCashEquivalentsAtCarryingValue": _usd(_instant(30e9, 2024)),
                "LongTermDebtNoncurrent": _usd(_instant(85e9, 2024)),
                "LongTermDebtCurrent": _usd(_instant(10e9, 2024)),
            },
        },
    }


class FakeResponse:
    """Minimal stand-in for `requests.Response`."""

    def __init__(self, payload: Any, status: int = 200) -> None:
        """Store the JSON payload and HTTP status."""

        self._payload = payload
        self.status_code = status

    def raise_for_status(self) -> None:
        """Raise on non-2xx statuses like requests does."""

        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> Any:
        """Return the JSON payload."""

        return self._payload


class FakeSession:
    """Fake `requests.Session` serving canned SEC responses."""

    def __init__(self, routes: dict[str, FakeResponse]) -> None:
        """Store URL → response routes."""

        self.routes = routes
        self.headers: dict[str, str] = {}
        self.requested: list[str] = []

    def get(self, url: str, timeout: float | None = None) -> FakeResponse:
        """Return the canned response for `url`."""

        self.requested.append(url)
        if url not in self.routes:
            return FakeResponse({}, status=404)
        return self.routes[url]


@pytest.fixture(autouse=True)
def _clear_ticker_cache() -> None:
    """Reset the module-level ticker → CIK cache between tests."""

    edgar._ticker_map_cache.clear()


def test_extract_financials_uses_latest_annual_values() -> None:
    """Latest 10-K values are selected, restatements win, and quarterly facts are ignored."""

    result = edgar.extract_financials(sample_company_facts())
    fin = result["financials"]

    assert fin["historical_revenue"] == 391e9
    assert fin["fiscal_year_end"] == "2024-09-30"
    assert fin["revenue_history"] == {"2024-09-30": 391e9, "2023-09-30": 380e9}
    assert fin["debt"] == 95e9
    assert fin["cash"] == 30e9
    assert fin["net_income"] == 95e9
    assert fin["equity"] == 57e9
    assert fin["shares_outstanding"] == 15e9
    assert fin["tax_rate"] == pytest.approx(25 / 120)
    assert fin["capex_pct_revenue"] == pytest.approx(9e9 / 391e9)
    # working capital excludes cash and current debt, which AV2 models separately
    assert fin["current_assets_pct_revenue"] == pytest.approx((150e9 - 30e9) / 391e9)
    assert fin["current_liabilities_pct_revenue"] == pytest.approx((175e9 - 10e9) / 391e9)
    assert fin["dividend_payout_pct"] == pytest.approx(15 / 95)
    # EBIT implied by AV2's cost structure matches reported operating income
    implied_ebit = 391e9 * (1 - fin["cogs_pct_revenue"] - fin["opex_pct_revenue"] - fin["da_pct_revenue"])
    assert implied_ebit == pytest.approx(120e9)

    opening = result["opening_balance_sheet"]
    assert opening == {"assets": 365e9, "liabilities": 308e9, "equity": 57e9}
    assert result["missing_fields"] == []


def test_extract_financials_handles_tag_switch_and_stale_values() -> None:
    """The newest fiscal year wins across tags, and values from older years are not mixed in."""

    facts = sample_company_facts()
    gaap = facts["facts"]["us-gaap"]
    gaap["Revenues"] = _usd(_duration(250e9, 2018), _duration(265e9, 2019))
    gaap["CashAndCashEquivalentsAtCarryingValue"] = _usd(_instant(25e9, 2019))
    del gaap["LongTermDebtNoncurrent"], gaap["LongTermDebtCurrent"]

    result = edgar.extract_financials(facts)
    fin = result["financials"]

    assert fin["historical_revenue"] == 391e9
    assert fin["fiscal_year_end"] == "2024-09-30"
    assert "cash" not in fin and "cash" in result["missing_fields"]
    assert "debt" not in fin and "interest_rate" in result["missing_fields"]


def test_total_debt_does_not_double_count_overlapping_tags() -> None:
    """`LongTermDebt` (incl. current maturities) is combined only with short-term borrowings."""

    facts = sample_company_facts()
    gaap = facts["facts"]["us-gaap"]
    del gaap["LongTermDebtNoncurrent"]
    gaap["LongTermDebt"] = _usd(_instant(95e9, 2024))
    gaap["CommercialPaper"] = _usd(_instant(5e9, 2024))

    assert edgar.extract_financials(facts)["financials"]["debt"] == 100e9


def test_bank_revenue_tag_is_recognised() -> None:
    """Banks report revenue as `RevenuesNetOfInterestExpense`."""

    facts = sample_company_facts()
    gaap = facts["facts"]["us-gaap"]
    del gaap["RevenueFromContractWithCustomerExcludingAssessedTax"]
    gaap["Revenues"] = _usd(_duration(150e9, 2019))
    gaap["RevenuesNetOfInterestExpense"] = _usd(_duration(180e9, 2024))

    fin = edgar.extract_financials(facts)["financials"]
    assert fin["historical_revenue"] == 180e9
    assert fin["fiscal_year_end"] == "2024-09-30"


def test_stale_revenue_is_rejected() -> None:
    """Revenue only available for years before the latest balance sheet raises instead of modelling old data."""

    facts = sample_company_facts()
    gaap = facts["facts"]["us-gaap"]
    del gaap["RevenueFromContractWithCustomerExcludingAssessedTax"]
    gaap["Revenues"] = _usd(_duration(150e9, 2019))
    gaap["Assets"]["units"]["USD"].append(_instant(100e9, 2019))

    with pytest.raises(edgar.EdgarError, match="stale"):
        edgar.extract_financials(facts)


def test_ratios_above_one_are_sent_as_amounts() -> None:
    """Balance-sheet items larger than revenue are passed as dollar amounts so AV2 does not scale them twice."""

    facts = sample_company_facts()
    facts["facts"]["us-gaap"]["AssetsCurrent"] = _usd(_instant(500e9, 2024))

    package = edgar.extract_financials(facts)
    assert package["financials"]["current_assets_pct_revenue"] == 470e9

    model = ThreeStatementModel({**package, "market": {"beta": 1.0}})
    assert model.inputs.current_assets_pct == pytest.approx(470e9 / 391e9)


def test_debt_missing_without_long_term_tag() -> None:
    """Current borrowings alone are not reported as total debt."""

    facts = sample_company_facts()
    del facts["facts"]["us-gaap"]["LongTermDebtNoncurrent"]

    result = edgar.extract_financials(facts)
    assert "debt" not in result["financials"]
    assert "debt" in result["missing_fields"]
    # the current portion is still excluded from operating current liabilities
    assert result["financials"]["current_liabilities_pct_revenue"] == pytest.approx((175e9 - 10e9) / 391e9)


def test_extracted_financials_produce_balanced_av2_model() -> None:
    """AV2's three-statement model balances on SEC-derived inputs instead of defaults."""

    package = edgar.extract_financials(sample_company_facts())
    package["market"] = {"beta": 1.1}
    model = ThreeStatementModel(package)

    assert model.inputs.historical_revenue == 391e9
    assert model.check_balance() is True


def test_extract_financials_requires_core_fields() -> None:
    """Missing revenue is an error rather than a silent default."""

    facts = sample_company_facts()
    del facts["facts"]["us-gaap"]["RevenueFromContractWithCustomerExcludingAssessedTax"]
    with pytest.raises(edgar.EdgarError, match="revenue"):
        edgar.extract_financials(facts)


def test_fetch_company_financials_resolves_cik_and_sends_user_agent() -> None:
    """The ticker is resolved to a zero-padded CIK and the SEC User-Agent is sent."""

    session = FakeSession({
        edgar.SEC_TICKER_MAP_URL: FakeResponse({"0": {"cik_str": 320193, "ticker": "EXMP", "title": "Example Corp"}}),
        "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json": FakeResponse(sample_company_facts()),
    })

    result = edgar.fetch_company_financials("exmp", user_agent="Example Research ops@example.com", session=session)

    assert result["cik"] == 320193
    assert result["entity_name"] == "Example Corp"
    assert result["financials"]["historical_revenue"] == 391e9
    assert session.headers["User-Agent"] == "Example Research ops@example.com"


def test_fetch_company_financials_errors() -> None:
    """Unknown tickers, HTTP failures, and missing User-Agent raise `EdgarError`."""

    ticker_map = FakeResponse({"0": {"cik_str": 1, "ticker": "AAA", "title": "A"}})
    with pytest.raises(edgar.EdgarError, match="not found"):
        edgar.fetch_company_financials("ZZZ", user_agent="X x@example.com", session=FakeSession({edgar.SEC_TICKER_MAP_URL: ticker_map}))
    with pytest.raises(edgar.EdgarError, match="request failed"):
        edgar.fetch_company_financials("AAA", user_agent="X x@example.com", session=FakeSession({edgar.SEC_TICKER_MAP_URL: ticker_map}))
    with pytest.raises(edgar.EdgarError, match="SEC_USER_AGENT"):
        edgar.fetch_company_financials("AAA", user_agent="", session=FakeSession({}))


def test_fetch_filings_uses_downloader_v5_api(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`fetch_filings` passes company/email/folder and `limit`, and returns downloaded paths."""

    calls: dict[str, Any] = {"get": []}

    class FakeDownloader:
        """Fake `sec_edgar_downloader.Downloader` writing the v5 folder layout."""

        def __init__(self, company_name: str, email_address: str, download_folder: Path | None = None) -> None:
            """Record constructor arguments."""

            calls["init"] = (company_name, email_address, download_folder)
            self.folder = Path(download_folder)

        def get(self, form: str, ticker: str, *, limit: int | None = None, download_details: bool = True) -> int:
            """Write a full-submission.txt for the requested form."""

            calls["get"].append((form, ticker, limit, download_details))
            target = self.folder / "sec-edgar-filings" / ticker / form / "0000320193-24-000123"
            target.mkdir(parents=True)
            (target / "full-submission.txt").write_text(f"{form} text", encoding="utf-8")
            return 1

    monkeypatch.setitem(sys.modules, "sec_edgar_downloader", types.SimpleNamespace(Downloader=FakeDownloader))

    paths = edgar.fetch_filings("aapl", user_agent="Example Research ops@example.com", download_folder=tmp_path)

    assert calls["init"] == ("Example Research", "ops@example.com", tmp_path)
    assert calls["get"] == [("10-K", "AAPL", 1, False), ("10-Q", "AAPL", 1, False)]
    assert [Path(p).read_text(encoding="utf-8") for p in paths] == ["10-K text", "10-Q text"]


def test_fetch_filings_wraps_downloader_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Downloader failures and a User-Agent without email surface as `EdgarError`."""

    class FailingDownloader:
        """Fake downloader whose `get` always fails."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            """Accept any constructor arguments."""

        def get(self, *args: Any, **kwargs: Any) -> int:
            """Simulate an SEC outage."""

            raise ConnectionError("sec down")

    monkeypatch.setitem(sys.modules, "sec_edgar_downloader", types.SimpleNamespace(Downloader=FailingDownloader))

    with pytest.raises(edgar.EdgarError, match="sec down"):
        edgar.fetch_filings("AAPL", user_agent="Example ops@example.com", download_folder=tmp_path)
    with pytest.raises(edgar.EdgarError, match="email"):
        edgar.fetch_filings("AAPL", user_agent="Example Research", download_folder=tmp_path)
