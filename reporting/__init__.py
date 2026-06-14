"""Report rendering and PDF generation.

This package contains the template-based report rendering pipeline,
including Jinja2 markdown templates and pandoc PDF generation.
"""

from .renderer import render, RendererError

__all__ = ["render", "RendererError"]
