"""Confidence scoring helpers for LLM responses.

The router uses this module to decide whether an Ollama result is good enough
to keep or whether Claude should take over the request.
"""

from __future__ import annotations

from collections.abc import Mapping
from numbers import Real
from typing import Any


def compute_confidence(response: Mapping[str, Any], schema: Mapping[str, Any]) -> float:
    """Compute a bounded confidence score for a model response.

    The score starts at 1.0 and is reduced for missing required fields,
    explicitly null required fields, and domain-rule violations.
    """

    payload = dict(response or {})
    schema_dict = dict(schema or {})

    missing_required_fields = 0
    null_required_fields = 0

    required_fields = schema_dict.get("required") or []
    for field_name in required_fields:
        if field_name not in payload:
            missing_required_fields += 1
        elif payload[field_name] is None:
            null_required_fields += 1

    score = 1.0
    score -= missing_required_fields * 0.15
    score -= null_required_fields * 0.10

    if _domain_logic_check_fails(payload, schema_dict):
        score -= 0.25

    return max(0.0, min(1.0, score))


def _domain_logic_check_fails(response: Mapping[str, Any], schema: Mapping[str, Any]) -> bool:
    """Return True when any domain consistency check fails."""

    return not (
        rating_return_direction(response)
        and confidence_in_range(response)
        and regime_is_valid(response, schema)
    )


def rating_return_direction(response: Mapping[str, Any]) -> bool:
    """Check that rating direction roughly matches the return signal."""

    rating = response.get("rating")
    if not isinstance(rating, str):
        return True

    expected_return: float | None = None
    if isinstance(response.get("expected_return"), Real):
        expected_return = float(response["expected_return"])
    elif isinstance(response.get("target_price"), Real) and isinstance(response.get("current_price"), Real):
        current_price = float(response["current_price"])
        if current_price != 0:
            expected_return = (float(response["target_price"]) - current_price) / current_price

    if expected_return is None:
        return True

    if rating == "BUY":
        return expected_return >= 0.0
    if rating == "SELL":
        return expected_return <= 0.0
    if rating == "HOLD":
        return abs(expected_return) <= 0.15
    return True


def confidence_in_range(response: Mapping[str, Any]) -> bool:
    """Check that any declared confidence value sits inside [0, 1]."""

    if "confidence" not in response:
        return True

    value = response.get("confidence")
    if not isinstance(value, Real):
        return False
    return 0.0 <= float(value) <= 1.0


def regime_is_valid(response: Mapping[str, Any], schema: Mapping[str, Any]) -> bool:
    """Check that any declared regime value is plausible or enum-compliant."""

    if "regime" not in response:
        return True

    regime = response.get("regime")
    if not isinstance(regime, str) or not regime.strip():
        return False

    properties = schema.get("properties") if isinstance(schema.get("properties"), Mapping) else {}
    regime_schema = properties.get("regime") if isinstance(properties, Mapping) else {}
    if isinstance(regime_schema, Mapping):
        enum_values = regime_schema.get("enum")
        if isinstance(enum_values, list) and enum_values:
            return regime in enum_values

    return True


__all__ = ["compute_confidence", "rating_return_direction", "confidence_in_range", "regime_is_valid"]