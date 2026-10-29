"""Unit tests for pricing/usage accounting models."""

from __future__ import annotations

from upgradepilot.models import CostRecord, LLMResponse, TokenUsage


def test_cost_record_tracks_tokens_and_cost() -> None:
    ledger = CostRecord()
    ledger.add_snapshot(100, 50)
    ledger.add_cost(0.05)
    ledger.add_snapshot(10, 0)
    ledger.add_cost(0.01)
    ledger.add_snapshot(1, 1)
    ledger.add_cost(0.005)

    assert ledger.calls == 3
    assert ledger.total_prompt_tokens == 111
    assert ledger.total_completion_tokens == 51
    assert ledger.total_cost_usd == 0.065


def test_llm_response_defaults() -> None:
    resp = LLMResponse()
    assert resp.content == ""
    assert resp.usage == TokenUsage()
    assert resp.raw is None
