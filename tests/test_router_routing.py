"""Tests for the LLM routing rules implemented in LLMRouter."""

from __future__ import annotations

from llm.router import LLMRouter


def test_select_provider_special_cases():
    r = LLMRouter()
    assert r.select_provider("pm1_thesis") == r.LLM_CLAUDE
    assert r.select_provider("av1") is None
    assert r.select_provider("av2") is None
    assert r.select_provider("pm2") is None


def test_select_provider_default():
    r = LLMRouter()
    assert r.select_provider("rs1") == r.LLM_OLLAMA


def test_compute_confidence_bounds():
    r = LLMRouter()
    assert r.compute_confidence(0, 0, False) == 1.0
    assert r.compute_confidence(10, 10, True) == 0.0
