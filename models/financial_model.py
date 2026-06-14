"""Deterministic three-statement financial model used by AV2.

This module turns the AV1 `DataPackage` into a self-consistent five-year
projection across the income statement, balance sheet, and cash flow
statement. The implementation is intentionally deterministic so it can be
unit tested without live market data, while still allowing richer inputs when
they are available in the data package.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import pandas as pd
import yaml


SCENARIO_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "scenarios.yaml"
ERP_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "damodaran_erp.yaml"


@dataclass(frozen=True)
class ProjectionInputs:
    """Normalized financial assumptions extracted from a data package."""

    historical_revenue: float
    revenue_growth: list[float]
    cogs_pct: float
    opex_pct: float
    da_pct: float
    tax_rate: float
    interest_rate: float
    debt: float
    cash: float
    current_assets_pct: float
    current_liabilities_pct: float
    net_ppe_pct: float
    capex_pct: float
    dividend_payout_pct: float
    debt_amortization_pct: float
    opening_assets: float | None
    opening_liabilities: float | None
    opening_equity: float | None
    market_beta: float
    risk_free_rate: float
    erp: float


def _load_yaml_file(path: Path) -> dict[str, Any]:
    """Load a YAML file if it exists, otherwise return an empty mapping."""

    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    return loaded if isinstance(loaded, dict) else {}


def _coerce_float(value: Any, default: float) -> float:
    """Convert a value to `float`, returning `default` when conversion fails."""

    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_float_list(value: Any, default: list[float], length: int = 5) -> list[float]:
    """Convert a scalar or sequence into a five-element float list."""

    if value is None:
        return list(default)
    if isinstance(value, (int, float)):
        return [float(value)] * length
    if isinstance(value, (list, tuple)):
        values: list[float] = []
        for idx, item in enumerate(value):
            fallback = default[idx] if idx < len(default) else default[-1]
            values.append(_coerce_float(item, fallback))
        if len(values) < length:
            fill_value = values[-1] if values else default[-1]
            values.extend([fill_value] * (length - len(values)))
        return values[:length]
    return list(default)


def _percent_of_revenue(value: Any, revenue: float, default_pct: float) -> float:
    """Normalize an amount or percentage into a revenue ratio."""

    if value is None:
        return default_pct
    numeric = _coerce_float(value, revenue * default_pct)
    if revenue == 0:
        return default_pct
    if abs(numeric) <= 1.0:
        return numeric
    return numeric / revenue


@lru_cache(maxsize=1)
def _load_scenarios() -> dict[str, Any]:
    """Load scenario assumptions from `config/scenarios.yaml`."""

    return _load_yaml_file(SCENARIO_CONFIG_PATH)


@lru_cache(maxsize=1)
def _load_erp() -> float:
    """Load Damodaran ERP from config, falling back to a conservative default."""

    loaded = _load_yaml_file(ERP_CONFIG_PATH)
    for key in ("erp", "equity_risk_premium", "market_erp", "default"):
        if key in loaded:
            return _coerce_float(loaded.get(key), 0.055)
    if loaded:
        first_value = next(iter(loaded.values()))
        return _coerce_float(first_value, 0.055)
    return 0.055


class ThreeStatementModel:
    """Five-year deterministic model derived from an AV1 data package."""

    def __init__(self, data_package: Any) -> None:
        """Store the input data package and pre-compute normalized inputs."""

        self.data_package = data_package
        self.payload = self._extract_payload(data_package)
        self.inputs = self._normalize_inputs(self.payload)
        self._projection_cache: dict[str, dict[str, pd.DataFrame]] = {}
        self._opening_balance_ok = self._validate_opening_balance()

    def build_income_statement(self) -> pd.DataFrame:
        """Build the base-case five-year income statement."""

        return self._project("base")["income_statement"].copy()

    def build_balance_sheet(self) -> pd.DataFrame:
        """Build the base-case five-year balance sheet."""

        return self._project("base")["balance_sheet"].copy()

    def build_cash_flow_statement(self) -> pd.DataFrame:
        """Build the base-case five-year cash flow statement."""

        return self._project("base")["cash_flow_statement"].copy()

    def check_balance(self) -> bool:
        """Return True only when each projected balance sheet balances within tolerance."""

        if not self._opening_balance_ok:
            return False

        balance_sheet = self.build_balance_sheet()
        for _, row in balance_sheet.iterrows():
            diff = abs(float(row["Assets"]) - float(row["Liabilities"]) - float(row["Equity"]))
            if diff >= 1000:
                return False
        return True

    def compute_wacc(self) -> float:
        """Compute a pragmatic WACC using available inputs or safe defaults."""

        risk_free_rate = self.inputs.risk_free_rate
        beta = self.inputs.market_beta
        erp = self.inputs.erp

        cost_of_equity = risk_free_rate + beta * erp

        debt = max(self.inputs.debt, 0.0)
        equity = max(self.inputs.opening_equity or self.inputs.opening_assets or 1.0, 1.0)
        total_capital = debt + equity
        debt_weight = debt / total_capital if total_capital else 0.0
        equity_weight = equity / total_capital if total_capital else 1.0

        interest_rate = max(self.inputs.interest_rate, 0.0)
        tax_rate = min(max(self.inputs.tax_rate, 0.0), 0.5)
        after_tax_cost_of_debt = interest_rate * (1.0 - tax_rate)

        wacc = equity_weight * cost_of_equity + debt_weight * after_tax_cost_of_debt
        return max(0.0, min(float(wacc), 1.0))

    def run_scenario(self, scenario: Literal["bear", "base", "bull"]) -> dict[str, Any]:
        """Run a named scenario and return the projected free cash flow stream."""

        projection = self._project(scenario)
        income = projection["income_statement"]
        cash_flow = projection["cash_flow_statement"]
        scenario_config = self._scenario_config_for(scenario)
        fcf_mult = _coerce_float(scenario_config.get("fcf_mult"), 1.0)

        return {
            "fcf": [float(value) * fcf_mult for value in cash_flow["FreeCashFlow"].tolist()],
            "ebitda_margin": [float(value) for value in (income["EBITDA"] / income["Revenue"]).tolist()],
            "capex": [float(value) for value in cash_flow["CapEx"].tolist()],
            "exit_multiple": float(scenario_config["exit_multiple"]),
        }

    def _extract_payload(self, data_package: Any) -> dict[str, Any]:
        """Return the underlying mapping from a row, ORM object, or raw dict."""

        if isinstance(data_package, dict):
            return data_package

        for attr in ("payload", "data", "model_dump"):
            if hasattr(data_package, attr):
                value = getattr(data_package, attr)
                if callable(value):
                    try:
                        extracted = value()
                    except TypeError:
                        continue
                    if isinstance(extracted, dict):
                        return extracted
                elif isinstance(value, dict):
                    return value

        return {}

    def _normalize_inputs(self, payload: dict[str, Any]) -> ProjectionInputs:
        """Normalize the incoming payload into deterministic model inputs."""

        financials = payload.get("financials") if isinstance(payload.get("financials"), dict) else payload
        market = payload.get("market") if isinstance(payload.get("market"), dict) else {}
        opening_bs = payload.get("opening_balance_sheet") if isinstance(payload.get("opening_balance_sheet"), dict) else {}

        historical_revenue = _coerce_float(
            financials.get("historical_revenue")
            or financials.get("revenue")
            or financials.get("revenue_ttm")
            or payload.get("historical_revenue")
            or payload.get("revenue")
            or 1_000_000_000.0,
            1_000_000_000.0,
        )

        base_growth = _coerce_float_list(
            financials.get("revenue_growth")
            or financials.get("growth_rate")
            or payload.get("revenue_growth")
            or payload.get("growth_rate"),
            default=[0.05, 0.045, 0.04, 0.035, 0.03],
        )

        gross_margin = financials.get("gross_margin") or payload.get("gross_margin")
        cogs_pct = _percent_of_revenue(
            financials.get("cogs_pct_revenue")
            or financials.get("cogs_ratio")
            or payload.get("cogs_pct_revenue")
            or payload.get("cogs_ratio"),
            historical_revenue,
            0.55,
        )
        if gross_margin is not None:
            cogs_pct = 1.0 - _coerce_float(gross_margin, 0.45)

        opex_pct = _percent_of_revenue(
            financials.get("opex_pct_revenue")
            or financials.get("opex_ratio")
            or payload.get("opex_pct_revenue")
            or payload.get("opex_ratio"),
            historical_revenue,
            0.18,
        )

        da_pct = _percent_of_revenue(
            financials.get("da_pct_revenue")
            or financials.get("da_ratio")
            or payload.get("da_pct_revenue")
            or payload.get("da_ratio"),
            historical_revenue,
            0.04,
        )

        tax_rate = _coerce_float(financials.get("tax_rate") or payload.get("tax_rate"), 0.21)
        interest_rate = _coerce_float(financials.get("interest_rate") or payload.get("interest_rate"), 0.05)
        debt = _coerce_float(financials.get("debt") or payload.get("debt") or market.get("total_debt"), 300_000_000.0)
        cash = _coerce_float(financials.get("cash") or payload.get("cash") or market.get("cash"), 150_000_000.0)
        current_assets_pct = _percent_of_revenue(
            financials.get("current_assets_pct_revenue")
            or financials.get("working_capital_assets_pct")
            or payload.get("current_assets_pct_revenue")
            or payload.get("working_capital_assets_pct"),
            historical_revenue,
            0.22,
        )
        current_liabilities_pct = _percent_of_revenue(
            financials.get("current_liabilities_pct_revenue")
            or financials.get("working_capital_liabilities_pct")
            or payload.get("current_liabilities_pct_revenue")
            or payload.get("working_capital_liabilities_pct"),
            historical_revenue,
            0.14,
        )
        net_ppe_pct = _percent_of_revenue(
            financials.get("net_ppe_pct_revenue")
            or financials.get("ppe_pct_revenue")
            or payload.get("net_ppe_pct_revenue")
            or payload.get("ppe_pct_revenue"),
            historical_revenue,
            0.35,
        )
        capex_pct = _percent_of_revenue(
            financials.get("capex_pct_revenue")
            or financials.get("capex_ratio")
            or payload.get("capex_pct_revenue")
            or payload.get("capex_ratio"),
            historical_revenue,
            0.06,
        )
        dividend_payout_pct = _coerce_float(
            financials.get("dividend_payout_pct") or payload.get("dividend_payout_pct"),
            0.20,
        )
        debt_amortization_pct = _coerce_float(
            financials.get("debt_amortization_pct") or payload.get("debt_amortization_pct"),
            0.03,
        )

        opening_assets = _coerce_float(opening_bs.get("assets") if opening_bs else payload.get("assets"), float("nan"))
        opening_liabilities = _coerce_float(opening_bs.get("liabilities") if opening_bs else payload.get("liabilities"), float("nan"))
        opening_equity = _coerce_float(opening_bs.get("equity") if opening_bs else payload.get("equity"), float("nan"))

        market_beta = _coerce_float(
            market.get("beta") or payload.get("beta") or financials.get("beta"),
            1.1,
        )
        risk_free_rate = _coerce_float(
            market.get("risk_free_rate") or payload.get("risk_free_rate") or market.get("dgs10"),
            0.045,
        )
        erp = _coerce_float(market.get("erp") or payload.get("erp"), _load_erp())

        return ProjectionInputs(
            historical_revenue=historical_revenue,
            revenue_growth=base_growth,
            cogs_pct=cogs_pct,
            opex_pct=opex_pct,
            da_pct=da_pct,
            tax_rate=tax_rate,
            interest_rate=interest_rate,
            debt=debt,
            cash=cash,
            current_assets_pct=current_assets_pct,
            current_liabilities_pct=current_liabilities_pct,
            net_ppe_pct=net_ppe_pct,
            capex_pct=capex_pct,
            dividend_payout_pct=dividend_payout_pct,
            debt_amortization_pct=debt_amortization_pct,
            opening_assets=None if pd.isna(opening_assets) else opening_assets,
            opening_liabilities=None if pd.isna(opening_liabilities) else opening_liabilities,
            opening_equity=None if pd.isna(opening_equity) else opening_equity,
            market_beta=market_beta,
            risk_free_rate=risk_free_rate,
            erp=erp,
        )

    def _validate_opening_balance(self) -> bool:
        """Check whether the supplied opening balance sheet already balances."""

        if self.inputs.opening_assets is None or self.inputs.opening_liabilities is None or self.inputs.opening_equity is None:
            return True
        diff = abs(self.inputs.opening_assets - self.inputs.opening_liabilities - self.inputs.opening_equity)
        return diff < 1000

    def _scenario_config_for(self, scenario: Literal["bear", "base", "bull"]) -> dict[str, Any]:
        """Return the normalized scenario config for a given scenario name."""

        loaded = _load_scenarios()
        default_configs = {
            "bear": {
                "revenue_growth": [0.00, 0.01, 0.015, 0.02, 0.02],
                "ebitda_margin_mult": 0.85,
                "capex_mult": 1.10,
                "fcf_mult": 0.85,
                "exit_multiple": 10.0,
            },
            "base": {
                "revenue_growth": [0.05, 0.045, 0.04, 0.035, 0.03],
                "ebitda_margin_mult": 1.0,
                "capex_mult": 1.0,
                "fcf_mult": 1.0,
                "exit_multiple": 12.0,
            },
            "bull": {
                "revenue_growth": [0.07, 0.065, 0.06, 0.055, 0.05],
                "ebitda_margin_mult": 1.10,
                "capex_mult": 0.95,
                "fcf_mult": 1.10,
                "exit_multiple": 14.0,
            },
        }
        scenario_data = loaded.get(scenario, {}) if isinstance(loaded, dict) else {}
        fallback = default_configs[scenario]

        return {
            "revenue_growth": _coerce_float_list(scenario_data.get("revenue_growth"), fallback["revenue_growth"]),
            "ebitda_margin_mult": _coerce_float(scenario_data.get("ebitda_margin_mult"), fallback["ebitda_margin_mult"]),
            "capex_mult": _coerce_float(scenario_data.get("capex_mult"), fallback["capex_mult"]),
            "fcf_mult": _coerce_float(scenario_data.get("fcf_mult"), fallback["fcf_mult"]),
            "exit_multiple": _coerce_float(scenario_data.get("exit_multiple"), fallback["exit_multiple"]),
        }

    def _project(self, scenario: Literal["bear", "base", "bull"]) -> dict[str, pd.DataFrame]:
        """Build and cache the three statements for a given scenario."""

        if scenario in self._projection_cache:
            return self._projection_cache[scenario]

        scenario_config = self._scenario_config_for(scenario)
        growth_rates = scenario_config["revenue_growth"]

        years = [f"FY{year}" for year in range(1, 6)]

        income_rows: list[dict[str, float]] = []
        balance_rows: list[dict[str, float]] = []
        cash_rows: list[dict[str, float]] = []

        prior_revenue = self.inputs.historical_revenue
        prior_cash = self.inputs.cash
        prior_debt = self.inputs.debt
        prior_equity = self.inputs.opening_equity if self.inputs.opening_equity is not None else max(self.inputs.historical_revenue * 0.45, 1.0)
        prior_net_ppe = self.inputs.historical_revenue * self.inputs.net_ppe_pct
        prior_current_assets = prior_revenue * self.inputs.current_assets_pct
        prior_current_liabilities = prior_revenue * self.inputs.current_liabilities_pct
        prior_wc = prior_current_assets - prior_current_liabilities

        for idx, year in enumerate(years):
            growth_rate = growth_rates[idx]
            revenue = prior_revenue * (1.0 + growth_rate)
            cogs = revenue * self.inputs.cogs_pct
            gross_profit = revenue - cogs
            opex = revenue * self.inputs.opex_pct * scenario_config["ebitda_margin_mult"]
            da = revenue * self.inputs.da_pct
            ebitda = gross_profit - opex
            ebit = ebitda - da
            interest_expense = max(prior_debt, self.inputs.debt) * self.inputs.interest_rate * 0.5
            pre_tax_income = ebit - interest_expense
            tax_expense = max(pre_tax_income, 0.0) * self.inputs.tax_rate
            net_income = pre_tax_income - tax_expense

            capex = revenue * self.inputs.capex_pct * scenario_config["capex_mult"]
            current_assets = revenue * self.inputs.current_assets_pct
            current_liabilities = revenue * self.inputs.current_liabilities_pct
            wc = current_assets - current_liabilities
            wc_change = wc - prior_wc

            operating_cf = net_income + da - wc_change
            investing_cf = -capex

            equity = prior_equity + net_income - (net_income * self.inputs.dividend_payout_pct)
            debt = max(prior_debt * (1.0 - self.inputs.debt_amortization_pct), 0.0)
            net_ppe = max(prior_net_ppe + capex - da, 0.0)

            non_cash_assets = current_assets + net_ppe
            liabilities = debt + current_liabilities
            cash = liabilities + equity - non_cash_assets
            financing_cf = cash - prior_cash - operating_cf - investing_cf
            free_cash_flow = operating_cf + investing_cf

            income_rows.append(
                {
                    "Revenue": revenue,
                    "COGS": cogs,
                    "GrossProfit": gross_profit,
                    "OpEx": opex,
                    "EBITDA": ebitda,
                    "DA": da,
                    "EBIT": ebit,
                    "InterestExpense": interest_expense,
                    "TaxExpense": tax_expense,
                    "NetIncome": net_income,
                }
            )
            balance_rows.append(
                {
                    "Cash": cash,
                    "CurrentAssets": current_assets,
                    "NetPPE": net_ppe,
                    "Assets": cash + non_cash_assets,
                    "CurrentLiabilities": current_liabilities,
                    "Debt": debt,
                    "Liabilities": liabilities,
                    "Equity": equity,
                }
            )
            cash_rows.append(
                {
                    "OperatingCF": operating_cf,
                    "InvestingCF": investing_cf,
                    "FinancingCF": financing_cf,
                    "FreeCashFlow": free_cash_flow,
                    "EndingCash": cash,
                    "CapEx": capex,
                    "WorkingCapitalChange": wc_change,
                }
            )

            prior_revenue = revenue
            prior_cash = cash
            prior_debt = debt
            prior_equity = equity
            prior_net_ppe = net_ppe
            prior_wc = wc

        projection = {
            "income_statement": pd.DataFrame(income_rows, index=years),
            "balance_sheet": pd.DataFrame(balance_rows, index=years),
            "cash_flow_statement": pd.DataFrame(cash_rows, index=years),
        }
        self._projection_cache[scenario] = projection
        return projection


__all__ = ["ThreeStatementModel"]