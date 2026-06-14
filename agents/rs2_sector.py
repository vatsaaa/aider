"""RS2 Sector Agent

This agent consumes macro regime outputs from `stage:rs1:output`, scores the
7 configured sectors for opportunity given the macro regime, and emits an
`M3SectorOutput` onto `stage:rs2:output`.

The agent loads `config/sectors.yaml` to obtain the canonical sector list,
primary valuation multiples, and screening metrics. It renders a prompt via
`config/prompts/rs2_sector.j2` and routes the prompt to the centralized LLM
router using `self.call_llm()`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from core.agent_base import BaseAgent
from core.bus import Message
from core.schemas import M3SectorOutput, M2MacroOutput


class RS2SectorAgent(BaseAgent):
    """Sector scoring agent (RS2).

    Class attributes define the input/output streams and consumer group.
    """

    stream_in = "stage:rs1:output"
    stream_out = "stage:rs2:output"
    group_name = "rs2-group"
    agent_name = "rs2_sector"

    SECTORS_PATH = Path("config/sectors.yaml")
    PROMPT_PATH = Path("config/prompts/rs2_sector.j2")

    def process(self, message: Message) -> M3SectorOutput:
        """Process an incoming `stage:rs1:output` message and return `M3SectorOutput`.

        Steps:
        - Parse `M2MacroOutput` from the message payload.
        - Load sector definitions from `config/sectors.yaml`.
        - Render the sector prompt and call the LLM.
        - Validate the response as `M3SectorOutput` and return it.
        """

        # Parse M2
        m2 = M2MacroOutput.model_validate(message.payload)

        # Load sectors
        sectors = self._load_sectors()

        # Render prompt
        system_prompt, user_prompt = self._render_prompt(m2, sectors)

        # Call LLM
        raw = self.call_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_schema=M3SectorOutput.model_json_schema(),
            max_tokens=800,
        )

        if isinstance(raw, str):
            payload = json.loads(raw)
        else:
            payload = dict(raw)

        m3 = M3SectorOutput.model_validate(payload)

        # Sanity check: sector_scores must have exactly the configured number
        if len(m3.sector_scores) != len(sectors):
            raise ValueError("sector_scores length does not match configured sectors")

        return m3

    def _load_sectors(self) -> Dict[str, Any]:
        """Load the sector definitions from `config/sectors.yaml`.

        Returns a mapping of sector name to its properties.
        """

        try:
            import yaml
        except Exception as exc:
            raise RuntimeError("PyYAML is required to load sector definitions") from exc

        path = self.SECTORS_PATH
        if not path.exists():
            raise RuntimeError(f"sectors file not found: {path}")

        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)

        # Expect a top-level list of sectors
        sectors = {s["name"]: s for s in data}
        return sectors

    def _render_prompt(self, m2: M2MacroOutput, sectors: Dict[str, Any]) -> tuple[str, str]:
        """Render the system and user prompts for the sector LLM call.

        The user prompt contains the regime, sector overweights, and full
        sector definitions.
        """

        try:
            from jinja2 import Environment, FileSystemLoader
        except Exception:
            raise RuntimeError("jinja2 is required to render prompts")

        if self.PROMPT_PATH.exists():
            env = Environment(loader=FileSystemLoader(str(self.PROMPT_PATH.parent)))
            tpl = env.get_template(self.PROMPT_PATH.name)
            rendered = tpl.render(regime=m2.regime, overweights=m2.sector_overweights, sectors=sectors)
        else:
            rendered = (
                f"Regime: {m2.regime}\nOverweights: {m2.sector_overweights}\nSectors: {list(sectors.keys())}"
            )

        system_prompt = "You are an investment analyst. Score each sector for opportunity given the macro regime."
        user_prompt = rendered
        return system_prompt, user_prompt


__all__ = ["RS2SectorAgent"]
