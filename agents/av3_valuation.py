"""AV3 valuation agent.

This agent consumes the AV2 model output, computes DCF and peer valuation
outputs, stores the sensitivity grid on the model row, and emits an M7
valuation message downstream.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.agent_base import BaseAgent
from core.bus import Message
from core.exceptions import FatalError
from core.schemas import M6ModelOutput, M7ValuationOutput
from models.valuation import build_sensitivity_table, compute_dcf, compute_peer_multiple, derive_rating, _json_loads_if_needed


class AV3ValuationAgent(BaseAgent):
    """Agent that converts M6 model output into M7 valuation output."""

    stream_in = "stage:av2:output"
    stream_out = "stage:av3:output"
    group_name = "av3-group"
    agent_name = "av3_valuation"

    PROMPT_PATH = Path("config/prompts/av3_valuation_reasoning.j2")

    def process(self, message: Message) -> M7ValuationOutput:
        """Load model inputs, compute valuation outputs, and persist them."""

        m6 = M6ModelOutput.model_validate(message.payload)
        model_row = self._load_model_row(m6.model_id)
        data_package = self._load_data_package(message.pipeline_run_id)

        fcf_stream = self._extract_fcf_stream(model_row)
        dcf = compute_dcf(fcf_stream, m6.wacc)

        subject_metrics = self._subject_metrics(model_row, data_package)
        peer = compute_peer_multiple(message.ticker, subject_metrics, self.db, self.settings)

        shares_outstanding = self._shares_outstanding(data_package, model_row)
        net_debt = self._net_debt(data_package, model_row)
        current_price = self._current_price(data_package, shares_outstanding)

        dcf_equity_value = max(float(dcf["enterprise_value"]) - net_debt, 0.0)
        dcf_price = dcf_equity_value / shares_outstanding if shares_outstanding > 0 else 0.0
        peer_price = self._peer_price(peer, shares_outstanding, subject_metrics)

        target_price = (dcf_price + peer_price) / 2.0 if peer_price > 0 else dcf_price
        rating = derive_rating(current_price=current_price, target_price=target_price)

        sensitivity_table = build_sensitivity_table(fcf_stream)
        reasoning = self._generate_reasoning(
            ticker=message.ticker,
            rating=rating,
            target_price=target_price,
            current_price=current_price,
            dcf_value=dcf_price,
            peer_multiple_value=peer_price,
            metric_used=str(peer["metric_used"]),
        )

        output = M7ValuationOutput(
            rating=rating,
            target_price=float(target_price),
            dcf_value=float(dcf_price),
            peer_multiple_value=float(peer_price),
            model_id=m6.model_id,
            reasoning=reasoning,
        )

        self._persist_valuation(model_id=m6.model_id, output=output, sensitivity_table=sensitivity_table, dcf=dcf, peer=peer, current_price=current_price)
        return output

    def _load_model_row(self, model_id: str) -> dict[str, Any]:
        """Load the AV2 financial model row for the given model id."""

        row = self.repository.load_financial_model_by_id(model_id)
        if row is None:
            raise FatalError("financial_model_missing", run_id=model_id)

        payload = _json_loads_if_needed(row.get("payload"))
        scenarios = _json_loads_if_needed(row.get("scenarios"))
        if not isinstance(payload, dict):
            payload = {}
        payload["_db_scenarios"] = scenarios
        payload["_db_wacc"] = row.get("wacc")
        payload["_db_ticker"] = row.get("ticker")
        payload["_db_run_id"] = row.get("run_id")
        return payload

    def _load_data_package(self, run_id: str) -> dict[str, Any]:
        """Load the AV1 data package for the current pipeline run."""

        row = self.repository.load_latest_data_package_by_run_id(run_id)
        if row is None:
            raise FatalError("data_package_missing", run_id=run_id)

        payload = _json_loads_if_needed(row.get("payload"))
        if not isinstance(payload, dict):
            raise FatalError("data_package_invalid", run_id=run_id)
        payload.setdefault("ticker", row.get("ticker"))
        return payload

    def _extract_fcf_stream(self, model_row: dict[str, Any]) -> list[float]:
        """Extract the base-case FCF stream from the stored model payload."""

        scenarios = model_row.get("scenarios") or model_row.get("_db_scenarios") or {}
        scenarios = _json_loads_if_needed(scenarios)
        if not isinstance(scenarios, dict):
            raise FatalError("model_payload_invalid", run_id=str(model_row.get("_db_run_id") or ""))

        base = scenarios.get("base") or {}
        base = _json_loads_if_needed(base)
        fcf = base.get("fcf") if isinstance(base, dict) else None
        if not isinstance(fcf, list) or len(fcf) != 5:
            raise FatalError("model_fcf_missing", run_id=str(model_row.get("_db_run_id") or ""))
        return [float(value) for value in fcf]

    def _subject_metrics(self, model_row: dict[str, Any], data_package: dict[str, Any]) -> dict[str, float]:
        """Assemble the subject metrics used by the peer multiple calculation."""

        income_statement = model_row.get("income_statement") or model_row.get("cash_flow_statement") or {}
        income_statement = _json_loads_if_needed(income_statement)
        fy1_ebitda = 0.0
        if isinstance(income_statement, dict):
            first_year = income_statement.get("FY1") or income_statement.get("Year1") or next(iter(income_statement.values()), {})
            if isinstance(first_year, dict):
                fy1_ebitda = float(first_year.get("EBITDA") or first_year.get("ebitda") or 0.0)

        market = data_package.get("market") if isinstance(data_package.get("market"), dict) else {}
        financials = data_package.get("financials") if isinstance(data_package.get("financials"), dict) else {}
        opening = data_package.get("opening_balance_sheet") if isinstance(data_package.get("opening_balance_sheet"), dict) else {}

        shares_outstanding = self._shares_outstanding(data_package, model_row)
        equity = float(opening.get("equity") or financials.get("equity") or 0.0)
        net_income = float(financials.get("net_income") or financials.get("earnings") or 0.0)

        return {
            "ebitda": fy1_ebitda,
            "book_value_per_share": equity / shares_outstanding if shares_outstanding > 0 else equity,
            "book_value": equity,
            "earnings_per_share": net_income / shares_outstanding if shares_outstanding > 0 else net_income,
            "earnings": net_income,
            "revenue": float(financials.get("historical_revenue") or financials.get("revenue") or 0.0),
            "shares_outstanding": shares_outstanding,
            "market_cap": float(market.get("market_cap") or 0.0),
        }

    def _shares_outstanding(self, data_package: dict[str, Any], model_row: dict[str, Any]) -> float:
        """Return shares outstanding using the best available source."""

        market = data_package.get("market") if isinstance(data_package.get("market"), dict) else {}
        opening = data_package.get("opening_balance_sheet") if isinstance(data_package.get("opening_balance_sheet"), dict) else {}
        financials = data_package.get("financials") if isinstance(data_package.get("financials"), dict) else {}

        candidates = [market.get("shares_outstanding"), market.get("sharesOutstanding"), financials.get("shares_outstanding"), opening.get("shares_outstanding"), model_row.get("shares_outstanding")]
        for candidate in candidates:
            try:
                shares = float(candidate)
            except (TypeError, ValueError):
                continue
            if shares > 0:
                return shares
        return 1.0

    def _net_debt(self, data_package: dict[str, Any], model_row: dict[str, Any]) -> float:
        """Return net debt using the best available source."""

        financials = data_package.get("financials") if isinstance(data_package.get("financials"), dict) else {}
        opening = data_package.get("opening_balance_sheet") if isinstance(data_package.get("opening_balance_sheet"), dict) else {}

        debt = 0.0
        for candidate in [financials.get("debt"), opening.get("liabilities"), model_row.get("debt")]:
            try:
                debt = float(candidate)
            except (TypeError, ValueError):
                continue
            if debt > 0:
                break

        cash = 0.0
        for candidate in [financials.get("cash"), opening.get("cash"), model_row.get("cash")]:
            try:
                cash = float(candidate)
            except (TypeError, ValueError):
                continue
            if cash > 0:
                break

        return max(debt - cash, 0.0)

    def _current_price(self, data_package: dict[str, Any], shares_outstanding: float) -> float:
        """Derive the current share price from the data package or market data."""

        market = data_package.get("market") if isinstance(data_package.get("market"), dict) else {}
        market_cap = market.get("market_cap") or market.get("marketCap")
        try:
            market_cap_value = float(market_cap)
        except (TypeError, ValueError):
            market_cap_value = 0.0

        if market_cap_value > 0 and shares_outstanding > 0:
            return market_cap_value / shares_outstanding

        for candidate in [market.get("current_price"), market.get("currentPrice"), market.get("regularMarketPrice"), market.get("previousClose")]:
            try:
                price = float(candidate)
            except (TypeError, ValueError):
                continue
            if price > 0:
                return price

        try:
            import yfinance as yf
        except Exception:
            return 0.0

        ticker = data_package.get("ticker") or data_package.get("symbol") or ""
        try:
            info = getattr(yf.Ticker(str(ticker)), "info", {}) or {}
        except Exception:
            return 0.0

        for key in ("currentPrice", "regularMarketPrice", "previousClose"):
            try:
                price = float(info.get(key))
            except (TypeError, ValueError):
                continue
            if price > 0:
                return price
        return 0.0

    def _peer_price(self, peer: dict[str, Any], shares_outstanding: float, subject_metrics: dict[str, float]) -> float:
        """Convert the peer multiple output into a per-share price estimate."""

        multiple = float(peer["median_multiple"])
        if peer["metric_used"] == "P/B":
            return multiple * subject_metrics.get("book_value_per_share", 0.0)
        if peer["metric_used"] in {"PE", "P/E"}:
            return multiple * subject_metrics.get("earnings_per_share", 0.0)

        implied_value = float(peer["implied_value"])
        if shares_outstanding <= 0:
            return implied_value
        return implied_value / shares_outstanding

    def _generate_reasoning(
        self,
        *,
        ticker: str,
        rating: str,
        target_price: float,
        current_price: float,
        dcf_value: float,
        peer_multiple_value: float,
        metric_used: str,
    ) -> str:
        """Generate the three-sentence valuation rationale."""

        context = {
            "ticker": ticker,
            "rating": rating,
            "target_price": round(target_price, 2),
            "current_price": round(current_price, 2),
            "dcf_value": round(dcf_value, 2),
            "peer_multiple_value": round(peer_multiple_value, 2),
            "metric_used": metric_used,
        }
        user_prompt = self._render_reasoning_prompt(context)
        system_prompt = "You write concise valuation commentary in three sentences."

        try:
            response = self.call_llm(system_prompt=system_prompt, user_prompt=user_prompt, response_schema=None, max_tokens=200)
        except Exception:
            response = None

        if isinstance(response, dict):
            for key in ("reasoning", "text", "content", "message"):
                value = response.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        if isinstance(response, str) and response.strip():
            return response.strip()

        return (
            f"{ticker} screens as a {rating} because the DCF points to a target price of ${target_price:.2f} versus a current price of ${current_price:.2f}. "
            f"The peer multiple work uses {metric_used} and lands at ${peer_multiple_value:.2f} per share, which keeps the valuation anchored to the sector's trading context. "
            f"Taken together, the gap between the two methods supports a disciplined {rating} view rather than a hand-wavy call."
        )

    def _render_reasoning_prompt(self, context: dict[str, Any]) -> str:
        """Render the AV3 prompt template or a local fallback."""

        if self.PROMPT_PATH.exists():
            try:
                from jinja2 import Template

                return Template(self.PROMPT_PATH.read_text(encoding="utf-8")).render(**context)
            except Exception:
                pass
        return (
            f"Write exactly three sentences explaining why {context['ticker']} is rated {context['rating']}. "
            f"Mention the DCF, the peer multiple, the target price of {context['target_price']}, and the current price of {context['current_price']}."
        )

    def _persist_valuation(
        self,
        *,
        model_id: str,
        output: M7ValuationOutput,
        sensitivity_table: dict[str, dict[str, float]],
        dcf: dict[str, Any],
        peer: dict[str, Any],
        current_price: float,
    ) -> None:
        """Persist the valuation result back to the `financial_models` table."""

        valuation_payload = {
            "rating": output.rating,
            "target_price": output.target_price,
            "dcf_value": output.dcf_value,
            "peer_multiple_value": output.peer_multiple_value,
            "reasoning": output.reasoning,
            "current_price": current_price,
            "dcf": dcf,
            "peer": peer,
        }

        row = self.repository.load_financial_model_by_id(model_id)
        if row is None:
            raise FatalError("financial_model_missing", run_id=model_id)

        payload = _json_loads_if_needed(row.get("payload"))
        if not isinstance(payload, dict):
            payload = {}
        payload["valuation"] = valuation_payload

        self.repository.update_financial_model_valuation(
            model_id=model_id,
            payload=payload,
            sensitivity_table=sensitivity_table,
        )


__all__ = ["AV3ValuationAgent"]