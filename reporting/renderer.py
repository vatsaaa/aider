"""PDF renderer using pandoc.

This module provides a single `render` function that converts Markdown to a
PDF using `pandoc`. The output filename will include the `run_id` so callers
can reliably find artifacts created for a specific pipeline run.

The function raises `RendererError` when the pandoc subprocess exits with a
non-zero status.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Optional


class RendererError(RuntimeError):
    """Raised when the renderer fails to create a PDF."""


def render(markdown_text: str, run_id: str, template: Optional[str] = "reporting/templates/report.tex") -> str:
    """Render `markdown_text` to a PDF using `pandoc` and return its path.

    Args:
        markdown_text: The markdown source to render.
        run_id: Pipeline run identifier used in the output filename.
        template: Path to a pandoc LaTeX template (relative to repo).

    Returns:
        Absolute path to the generated PDF file.

    Raises:
        RendererError: If `pandoc` exits with a non-zero exit code.
    """

    # Create a temp directory to hold the input and output files.
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        input_path = tmpdir_path / f"report_{run_id}.md"
        output_path = tmpdir_path / f"report_{run_id}.pdf"

        input_path.write_text(markdown_text, encoding="utf-8")

        cmd = [
            "pandoc",
            str(input_path),
            "-o",
            str(output_path),
            "--pdf-engine=xelatex",
            "--template",
            str(template),
            "-V",
            "geometry:margin=2cm",
        ]

        proc = subprocess.run(cmd, capture_output=True)
        if proc.returncode != 0:
            raise RendererError(f"pandoc failed: {proc.returncode}: {proc.stderr.decode(errors='ignore')}")

        # Return absolute path as string
        return str(output_path.resolve())
