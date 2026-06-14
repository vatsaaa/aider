"""Financial models and valuation logic.

This package contains the deterministic three-statement financial model,
DCF and peer valuation computations, and sensitivity analysis tools.
"""

from .financial_model import ThreeStatementModel
from .valuation import compute_dcf, compute_peer_multiple, build_sensitivity_table, derive_rating

__all__ = ["ThreeStatementModel", "compute_dcf", "compute_peer_multiple", "build_sensitivity_table", "derive_rating"]
