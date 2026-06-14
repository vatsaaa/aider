"""RS1 Macro Agent

This agent consumes trigger events from `trigger:events`, classifies the
current macro regime using FRED series and the latest FOMC statement, and
publishes an `M2MacroOutput` onto `stage:rs1:output`.

Behavior:
- Parses incoming `M1TriggerEvent` payloads.
- Fetches and caches FRED series (4 hour TTL) and FOMC summary (24 hour TTL).
- Renders the `config/prompts/rs1_macro.j2` template and routes the prompt
  to the centralized LLM router via `self.call_llm()`.
- Validates the LLM output against `M2MacroOutput` and persists the
  classification to the `macro_regime` table.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Any, Dict, Optional

from sqlalchemy import text

from core.agent_base import BaseAgent
from core.bus import Message
from core.exceptions import FatalError
from core.schemas import M1TriggerEvent, M2MacroOutput


class RS1MacroAgent(BaseAgent):
    """Macro regime classification agent (RS1).

    Attributes set on the class control the streams and consumer group used
    by the base agent loop.
    """

    stream_in = "trigger:events"
    stream_out = "stage:rs1:output"
    group_name = "rs1-group"
    agent_name = "rs1_macro"

    FRED_SERIES = ("FEDFUNDS", "DGS10", "DGS2", "CPIAUCSL", "PCEPI", "NAPM")
    FRED_CACHE_KEY = "rs1:fred_data"
    FRED_TTL = 4 * 60 * 60  # 4 hours
    FOMC_CACHE_KEY = "rs1:fomc_summary"
    FOMC_TTL = 24 * 60 * 60  # 24 hours
    SECTOR_ROTATION_MATRIX_PATH = "config/sector_rotation_matrix.yaml"

    def process(self, message: Message) -> M2MacroOutput:
        """Process a single `Message` from the `trigger:events` stream.

        The method will either return a cached regime for non-macro company
        triggers (if the cached classification is fresh), or it will fetch
        data, call the LLM, validate the output, persist the result, and
        return the validated `M2MacroOutput`.
        """

        # Parse the M1 payload
        m1 = M1TriggerEvent.model_validate(message.payload)

        # If not a global macro trigger, check cached regime
        if m1.ticker != "__MACRO__":
            cached = self._get_recent_regime()
            if cached is not None:
                return cached

        # Fetch inputs
        fred = self._get_fred_data()
        fomc_summary = self._get_fomc_summary()

        # Render prompt
        sector_rotation_matrix = self._load_sector_rotation_matrix()
        system_prompt, user_prompt = self._render_prompt(fred, fomc_summary, sector_rotation_matrix, m1)

        # Call LLM
        raw = self.call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_schema=M2MacroOutput.model_json_schema(),
            max_tokens=1000,
        )

        # Normalize response into dict
        if isinstance(raw, str):
            payload = json.loads(raw)
        else:
            payload = dict(raw)

        # Validate schema
        m2 = M2MacroOutput.model_validate(payload)

        # Enforce the configured rotation matrix for the predicted regime
        self._validate_sector_rotation_matrix(m2, sector_rotation_matrix)

        # Confidence gating
        if m2.confidence < 0.5:
            raise FatalError("rs1_low_confidence")

        # Persist regime to DB
        self._persist_regime(m2)

        return m2

    # Helper methods
    def _get_fred_data(self) -> Dict[str, float]:
        """Return a dict of FRED series latest values, using Redis cache.

        The method caches results for 4 hours under `FRED_CACHE_KEY`.
        """

        try:
            cached = self.bus.get_cache(self.FRED_CACHE_KEY)
            if cached:
                return json.loads(cached)
        except Exception:
            cached = None

        # Lazy import of fredapi to avoid module import-time failures in tests
        try:
            from fredapi import Fred
        except Exception as exc:
            raise RuntimeError("fredapi is required to fetch FRED series") from exc

        fred = Fred(api_key=self.settings.FRED_API_KEY)
        out: Dict[str, float] = {}
        for series in self.FRED_SERIES:
            try:
                series_values = fred.get_series(series)
                if series_values is None:
                    continue
                if hasattr(series_values, "dropna"):
                    cleaned = series_values.dropna()
                    try:
                        value = float(cleaned.iloc[-1])
                    except Exception:
                        value = float(cleaned[-1]) if len(cleaned) else None
                elif isinstance(series_values, (list, tuple)):
                    value = float(series_values[-1]) if series_values else None
                else:
                    value = float(series_values)
            except Exception:
                value = None
            if value is not None:
                out[series] = value

        try:
            self.bus.set_cache(self.FRED_CACHE_KEY, json.dumps(out), ttl_seconds=self.FRED_TTL)
        except Exception:
            pass

        return out

    def _get_fomc_summary(self) -> str:
        """Scrape the most recent FOMC statement summary and cache it for 24h.

        The routine fetches the FOMC calendars page, follows the most recent
        meeting link, and extracts the first two paragraphs of the statement.
        """

        try:
            cached = self.bus.get_cache(self.FOMC_CACHE_KEY)
            if cached:
                return cached.decode() if isinstance(cached, (bytes, bytearray)) else cached
        except Exception:
            cached = None

        # Lazy imports
        try:
            import requests
            from bs4 import BeautifulSoup
        except Exception as exc:
            raise RuntimeError("requests and beautifulsoup4 are required for FOMC scraping") from exc

        cal_url = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
        try:
            resp = requests.get(cal_url, timeout=10)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            # Find the first meeting link under the calendars page
            link = soup.select_one(".panel .col-md-9 a") or soup.find("a")
            if not link or not link.get("href"):
                summary = ""
            else:
                href = link.get("href")
                if href.startswith("/"):
                    href = "https://www.federalreserve.gov" + href
                detail = requests.get(href, timeout=10)
                detail.raise_for_status()
                dsoup = BeautifulSoup(detail.text, "html.parser")
                p_tags = dsoup.select(".col-xs-12 p") or dsoup.find_all("p")
                paras = [p.get_text(strip=True) for p in p_tags if p.get_text(strip=True)]
                summary = "\n\n".join(paras[:2])
        except Exception:
            summary = ""

        try:
            self.bus.set_cache(self.FOMC_CACHE_KEY, summary, ttl_seconds=self.FOMC_TTL)
        except Exception:
            pass

        return summary

    def _load_sector_rotation_matrix(self) -> Dict[str, Dict[str, Any]]:
        """Load the explicit sector rotation matrix configuration."""

        try:
            import yaml
            from pathlib import Path

            path = Path(self.SECTOR_ROTATION_MATRIX_PATH)
            if not path.exists():
                return {}
            data = yaml.safe_load(path.read_text()) or {}
            if not isinstance(data, dict):
                return {}
            return data
        except Exception:
            return {}

    def _render_prompt(
        self,
        fred: Dict[str, float],
        fomc_summary: str,
        sector_rotation_matrix: Dict[str, Dict[str, Any]],
        m1: M1TriggerEvent,
    ) -> tuple[str, str]:
        """Render the system and user prompts from the template file.

        If the template file is missing, a minimal fallback prompt is used.
        """

        try:
            from jinja2 import Environment, FileSystemLoader
            from pathlib import Path

            tpl_path = Path("config/prompts/rs1_macro.j2")
            if tpl_path.exists():
                env = Environment(loader=FileSystemLoader(str(tpl_path.parent)))
                tpl = env.get_template(tpl_path.name)
                rendered = tpl.render(
                    fred=fred,
                    fomc_summary=fomc_summary,
                    sector_rotation_matrix=sector_rotation_matrix,
                    trigger=m1.model_dump(),
                )
            else:
                rendered = (
                    f"FRED:{fred}\nFOMC:{fomc_summary}\n"
                    f"SECTOR_ROTATION_MATRIX:{sector_rotation_matrix}\nTRIGGER:{m1.model_dump()}"
                )
        except Exception:
            rendered = (
                f"FRED:{fred}\nFOMC:{fomc_summary}\n"
                f"SECTOR_ROTATION_MATRIX:{sector_rotation_matrix}\nTRIGGER:{m1.model_dump()}"
            )

        system_prompt = "You are a macro economist. Classify the current macro regime."
        user_prompt = rendered
        return system_prompt, user_prompt

    def _persist_regime(self, m2: M2MacroOutput) -> None:
        """Persist the M2 classification to the `macro_regime` table."""

        self.repository.save_macro_regime(
            regime=m2.regime,
            confidence=float(m2.confidence),
            sector_overweights=m2.sector_overweights,
            sector_underweights=m2.sector_underweights,
            reasoning=m2.reasoning,
            classified_at=datetime.now(timezone.utc),
        )

    def _validate_sector_rotation_matrix(
        self,
        m2: M2MacroOutput,
        sector_rotation_matrix: Dict[str, Dict[str, Any]],
    ) -> None:
        """Ensure the LLM output matches the configured regime-specific overweights."""

        regime_cfg = sector_rotation_matrix.get(m2.regime)
        if not regime_cfg:
            raise FatalError(f"rs1_missing_sector_rotation_matrix:{m2.regime}")

        expected_overweights = regime_cfg.get("overweights") or []
        expected_underweights = regime_cfg.get("underweights") or []
        actual_overweights = m2.sector_overweights or []

        if sorted(actual_overweights) != sorted(expected_overweights):
            raise FatalError(
                "rs1_sector_rotation_mismatch_overweights"
            )

        actual_underweights = m2.sector_underweights or []
        if sorted(actual_underweights) != sorted(expected_underweights):
            raise FatalError(
                "rs1_sector_rotation_mismatch_underweights"
            )

    def _get_recent_regime(self) -> Optional[M2MacroOutput]:
        """Return a recent `M2MacroOutput` if one exists within the last 4 hours.

        Returns `None` if no recent classification is found.
        """

        row = self.repository.load_latest_macro_regime()
        if not row:
            return None

        # Parse classified_at and compute age
        try:
            classified_at = row.get("classified_at")
            if isinstance(classified_at, str):
                classified_at = datetime.fromisoformat(classified_at)
            age = datetime.now(timezone.utc) - classified_at
        except Exception:
            age = timedelta.max

        if age <= timedelta(hours=4):
            try:
                sector_overweights = row.get("sector_overweights") or []
                if isinstance(sector_overweights, str):
                    sector_overweights = json.loads(sector_overweights)
                sector_underweights = row.get("sector_underweights") or []
                if isinstance(sector_underweights, str):
                    sector_underweights = json.loads(sector_underweights)
            except Exception:
                sector_overweights = []
                sector_underweights = []
            return M2MacroOutput(
                regime=row.get("regime"),
                confidence=float(row.get("confidence") or 0.0),
                sector_overweights=sector_overweights,
                sector_underweights=sector_underweights,
                reasoning=row.get("reasoning"),
            )

        return None


__all__ = ["RS1MacroAgent"]
