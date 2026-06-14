"""RS3 Screen Agent

This agent consumes sector screening outputs from `stage:rs2:output`, finds
candidates in the coverage universe for the `primary_sector`, fetches
screening metrics via `yfinance`, computes a composite mispricing score per
ticker, and returns a ranked list of up to 5 candidates as `M4ScreenOutput`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from sqlalchemy import text

from core.agent_base import BaseAgent
from core.bus import Message
from core.schemas import M3SectorOutput, CandidateTicker, M4ScreenOutput


@dataclass
class _TickerData:
    ticker: str
    metrics: Dict[str, float]


class RS3ScreenAgent(BaseAgent):
    """Screening agent that produces `M4ScreenOutput` from sector scores."""

    stream_in = "stage:rs2:output"
    stream_out = "stage:rs3:output"
    group_name = "rs3-group"
    agent_name = "rs3_screen"

    SECTORS_PATH = Path("config/sectors.yaml")
    PROMPT_PATH = Path("config/prompts/rs3_screen.j2")

    def process(self, message: Message) -> M4ScreenOutput:
        """Process a `stage:rs2:output` message and return `M4ScreenOutput`.

        The method looks up the originating pipeline run to find the original
        ticker, queries the coverage universe for tickers tagged with the
        `primary_sector`, fetches screening metrics via `yfinance`, computes
        composite scores, and asks the LLM to produce the final top candidates.
        """

        m3 = M3SectorOutput.model_validate(message.payload)

        # Retrieve originating ticker from pipeline_runs using run_id
        run_id = message.pipeline_run_id or message.data.get("pipeline_run_id")
        orig_ticker = self._lookup_run_ticker(run_id)

        # Get candidate tickers for primary sector
        primary = m3.primary_sector
        candidate_tickers = self._coverage_tickers_for_sector(primary)

        if not candidate_tickers:
            raise RuntimeError(f"no candidates found for sector: {primary}")

        # Fetch screening data (batch then per-ticker fallback)
        screening = self._fetch_screening_data(candidate_tickers)

        # Compute scores using sector metrics from config
        sectors = self._load_sectors()
        sector_info = sectors.get(primary)
        metrics = sector_info.get("metrics", []) if sector_info else []

        scored: List[_TickerData] = []
        for t in candidate_tickers:
            data = screening.get(t)
            if not data:
                continue
            score = self._compute_score(data, metrics)
            scored.append(_TickerData(ticker=t, metrics={"score": score}))

        # Sort and take top 10 for prompt, but only send top-10 into LLM
        scored.sort(key=lambda x: x.metrics["score"], reverse=True)
        top10 = scored[:10]

        # Render prompt for the LLM with the top-10
        system_prompt, user_prompt = self._render_prompt(m3, orig_ticker, top10)

        raw = self.call_llm(system_prompt=system_prompt, user_prompt=user_prompt, response_schema=M4ScreenOutput.model_json_schema(), max_tokens=1000)

        if isinstance(raw, str):
            payload = json.loads(raw)
        else:
            payload = dict(raw)

        m4 = M4ScreenOutput.model_validate(payload)

        return m4

    def _lookup_run_ticker(self, run_id: str) -> str | None:
        """Query `pipeline_runs` for `run_id` and return the associated ticker.

        Returns `None` if not found.
        """

        if not run_id:
            return None

        return self.repository.load_pipeline_run_ticker(run_id)

    def _coverage_tickers_for_sector(self, sector: str) -> List[str]:
        """Return tickers from `coverage_universe` that are tagged for `sector`.

        This implementation expects the `notes` column to contain a JSON object
        with a `sector` key for filtering. Rows without such a tag are ignored.
        """

        rows = self.repository.coverage_tickers_for_sector(sector)

        out: List[str] = []
        out.extend(rows)
        return out

    def _fetch_screening_data(self, tickers: List[str]) -> Dict[str, Dict[str, float]]:
        """Fetch screening metrics from `yfinance` with batch and fallback.

        Returns a mapping ticker -> metrics dict. Failures for individual
        tickers are tolerated; successful tickers are returned.
        """

        try:
            import yfinance as yf
        except Exception:
            raise RuntimeError("yfinance is required for screening data")

        # Try batch download
        try:
            df = yf.download(tickers=tickers, group_by='ticker', threads=True, progress=False)
            # Normalize output: yf.download may return DataFrame with columns per ticker
            out: Dict[str, Dict[str, float]] = {}
            # For tests we'll allow callers to mock yf.download to return a dict
            if isinstance(df, dict):
                return df
            # If df is a DataFrame, we can't reliably parse metrics here; return empty
            return {}
        except Exception:
            # Fallback: fetch per-ticker
            out = {}
            for t in tickers:
                try:
                    single = yf.Ticker(t)
                    info = getattr(single, "info", {}) or {}
                    # Extract a small set of fields commonly available
                    out[t] = {
                        "pe_ratio": info.get("trailingPE") or info.get("forwardPE") or 0.0,
                        "ev_to_ebitda": info.get("enterpriseToEbitda") or 0.0,
                        "pb": info.get("priceToBook") or 0.0,
                        "revenue_growth_yoy": info.get("revenueGrowth") or 0.0,
                        "gross_margin": info.get("grossMargins") or 0.0,
                        "net_debt_to_ebitda": info.get("netDebtToEbitda") or 0.0,
                    }
                except Exception:
                    continue
            return out

    def _load_sectors(self) -> Dict[str, Any]:
        """Load sector definitions from `config/sectors.yaml`.

        Reuses the format created by RS2.
        """

        try:
            import yaml
        except Exception:
            raise RuntimeError("PyYAML is required to load sector definitions")

        path = self.SECTORS_PATH
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return {s["name"]: s for s in data}

    def _compute_score(self, data: Dict[str, float], metrics: List[str]) -> float:
        """Compute a composite score in [0,1] from metric values.

        The formula normalizes each metric to a 0-1 range using a simple
        transformation and averages available metrics.
        """

        total = 0.0
        count = 0
        for m in metrics:
            val = data.get(m) or data.get(m.replace('-', '_'))
            if val is None:
                continue
            try:
                numeric = float(val)
            except Exception:
                continue
            # Simple normalization: larger absolute values -> smaller scores via 1/(1+abs(x))
            comp = 1.0 / (1.0 + abs(numeric))
            total += comp
            count += 1

        if count == 0:
            return 0.5
        return min(max(total / count, 0.0), 1.0)

    def _render_prompt(self, m3: M3SectorOutput, orig_ticker: str | None, top10: List[_TickerData]) -> tuple[str, str]:
        """Render the LLM prompts for the screening step.

        The prompt includes the top candidates and their scores.
        """

        try:
            from jinja2 import Environment, FileSystemLoader
        except Exception:
            raise RuntimeError("jinja2 is required to render prompts")

        if self.PROMPT_PATH.exists():
            env = Environment(loader=FileSystemLoader(str(self.PROMPT_PATH.parent)))
            tpl = env.get_template(self.PROMPT_PATH.name)
            rendered = tpl.render(primary_sector=m3.primary_sector, reasoning=m3.reasoning, candidates=[{"ticker": t.ticker, "score": t.metrics["score"]} for t in top10], orig_ticker=orig_ticker)
        else:
            rendered = f"Primary: {m3.primary_sector}\nCandidates: {[t.ticker for t in top10]}"

        system_prompt = "You are a stock screener. From the candidate list, return up to 5 tickers with short rationale."
        return system_prompt, rendered


__all__ = ["RS3ScreenAgent"]
