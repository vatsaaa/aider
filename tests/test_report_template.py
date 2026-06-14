"""Tests for the PM1 report markdown and LaTeX templates."""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader


REPORT_TEMPLATE_DIR = Path("reporting/templates")


def _render_report(**context: object) -> str:
    """Render the PM1 markdown template with deterministic dummy data."""

    environment = Environment(loader=FileSystemLoader(str(REPORT_TEMPLATE_DIR)), autoescape=False)
    template = environment.get_template("base_report.md.j2")
    return template.render(**context)


def _dummy_context() -> dict[str, object]:
    """Return representative dummy data for the report template."""

    return {
        "ticker": "AAPL",
        "rating": "BUY",
        "target_price": 212.34,
        "date": "2026-05-31",
        "investment_thesis": "A clear catalyst and durable cash flow support the thesis.",
        "financial_summary_rows": [
            {"metric": "Revenue", "fy_minus_1": 100, "fy_0": 110, "fy_1": 120, "fy_2": 130},
            {"metric": "EBITDA", "fy_minus_1": 30, "fy_0": 33, "fy_1": 36, "fy_2": 39},
        ],
        "business_model": "The company monetizes a high-retention installed base.",
        "earnings_review": "Consensus beat on revenue, margins held steady.",
        "scenarios": {
            "bear": "Lower growth and margin pressure.",
            "base": "Mid-single-digit growth and stable margins.",
            "bull": "Acceleration in growth and modest margin expansion.",
        },
        "sensitivity_table": {
            "9.0%": {"2.0%": 100, "2.5%": 105, "3.0%": 110, "3.5%": 115},
            "10.0%": {"2.0%": 95, "2.5%": 100, "3.0%": 105, "3.5%": 110},
            "11.0%": {"2.0%": 90, "2.5%": 95, "3.0%": 100, "3.5%": 105},
            "12.0%": {"2.0%": 85, "2.5%": 90, "3.0%": 95, "3.5%": 100},
        },
        "sensitivity_growth_rates": ["2.0%", "2.5%", "3.0%", "3.5%"],
        "risk_factors": "Macro slowdown, supply chain pressure, and valuation compression.",
        "dcf_detail": "DCF present value and terminal value summary.",
        "peer_comp_table": "Peer median and relative multiple summary.",
        "run_id": "run-123",
        "model_id": "model-456",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def test_template_renders_all_sections() -> None:
    """The markdown template must emit every required section heading."""

    rendered = _render_report(**_dummy_context())

    required_sections = [
        "# AAPL — BUY | Target: $212.34 | 2026-05-31",
        "## Investment Thesis (Page 1)",
        "## Financial Summary Table",
        "## Business Model & Competitive Position",
        "## Earnings Review: Actual vs. Consensus",
        "## Three-Scenario Financial Model (Bear / Base / Bull)",
        "## WACC / Terminal Growth Sensitivity Table",
        "## Risk Factors",
        "## Appendix (DCF detail, peer comp table)",
        "Pipeline run ID: run-123 | Model ID: model-456",
    ]

    for section in required_sections:
        assert section in rendered


def test_template_footer_contains_run_id() -> None:
    """The report footer must include the pipeline run identifier."""

    rendered = _render_report(**_dummy_context())
    assert "Pipeline run ID: run-123" in rendered
    assert "Model ID: model-456" in rendered


@pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc is not installed")
@pytest.mark.skipif(shutil.which("xelatex") is None, reason="xelatex is not installed")
def test_pdf_renders_without_error(tmp_path: Path) -> None:
    """Pandoc should render the report template to a non-empty PDF."""

    markdown_path = tmp_path / "dummy_report.md"
    output_path = tmp_path / "test.pdf"
    markdown_path.write_text(_render_report(**_dummy_context()), encoding="utf-8")

    command = [
        "pandoc",
        str(markdown_path),
        "-o",
        str(output_path),
        "--pdf-engine=xelatex",
        "--template=reporting/templates/report.tex",
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)

    assert completed.returncode == 0, completed.stderr
    assert output_path.exists()
    assert output_path.stat().st_size > 0