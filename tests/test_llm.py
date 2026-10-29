"""Unit tests for the Token Factory LLM client.

Uses injected fake/mock httpx transports instead of network. The
preflight-cap test asserts the transport's request method is *never*
called when the run cap would be exceeded.
"""

from __future__ import annotations

import json

import httpx
import pytest

from upgradepilot.config import Settings
from upgradepilot.llm import (
    LLMClient,
    LLMClientError,
    SpendingCapExceeded,
    call_cost,
    estimate_prompt_tokens,
)
from upgradepilot.models import TokenUsage
from upgradepilot.tiers import ModelTier

# Pricing/params per live catalog (verified 2026-10-20)
CHEAP = ModelTier(
    role="cheap",
    model_id="nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
    context_window=262144,
    input_price_per_m=0.06,
    output_price_per_m=0.24,
    max_tokens=16,
)

HEAVY = ModelTier(
    role="strong",
    model_id="nvidia/Nemotron-3-Ultra-550b-a55b",
    context_window=1048576,
    input_price_per_m=1.0,
    output_price_per_m=3.0,
    max_tokens=4096,
)


def _settings(cap: float) -> Settings:
    return Settings(
        nebius_api_key="nab",
        tavily_api_key="tvly-x",
        token_cost_cap_usd=cap,
    )


def _success(usage_in: int = 12, usage_out: int = 7) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": CHEAP.model_id,
            "choices": [{"message": {"content": "OK!"}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": usage_in,
                "completion_tokens": usage_out,
                "total_tokens": usage_in + usage_out,
            },
        },
    )


def test_call_cost_math() -> None:
    usage = TokenUsage(prompt_tokens=1_000_000, completion_tokens=500_000)
    assert call_cost(usage, CHEAP) == pytest.approx(
        1_000_000 * 0.06 / 1_000_000 + 500_000 * 0.24 / 1_000_000
    )


def test_estimate_prompt_tokens_is_conservative() -> None:
    assert estimate_prompt_tokens([]) == 0
    short = estimate_prompt_tokens([{"role": "user", "content": "aaaa"}])
    long = estimate_prompt_tokens([{"role": "user", "content": "a" * 400}])
    assert short == 11
    assert long > short


def test_preflight_cap_blocks_call() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500, json={"detail": "internal"})

    client = LLMClient(
        _settings(cap=0.01),
        httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(SpendingCapExceeded):
        client.chat([{"role": "user", "content": "prompt " * 50}], HEAVY, max_tokens=4096)

    # Network was never touched: cap must block *before* the request.
    assert requests == []


def test_cap_blocks_followup_after_booking() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return _success(usage_in=1_000_000, usage_out=200_000)

    client = LLMClient(
        _settings(cap=0.08),
        httpx.Client(transport=httpx.MockTransport(handler)),
    )

    client.chat([{"role": "user", "content": "hi"}], CHEAP, max_tokens=1)
    assert client.cost.total_cost_usd > 0.08

    with pytest.raises(SpendingCapExceeded):
        client.chat([{"role": "user", "content": "hi"}], CHEAP, max_tokens=1)
    assert calls["n"] == 1


def test_429_then_success_with_retry() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return _success()

    client = LLMClient(
        _settings(cap=2.0),
        httpx.Client(transport=httpx.MockTransport(handler)),
    )

    response = client.chat([{"role": "user", "content": "hi"}], CHEAP, max_tokens=5)

    assert calls["n"] == 2
    assert response.content == "OK!"
    assert response.usage.prompt_tokens == 12
    assert response.raw is not None
    assert client.cost.calls == 1
    assert client.cost.total_prompt_tokens == 12


def test_401_is_non_retryable() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(401, json={"detail": "Unauthorized"})

    client = LLMClient(
        Settings(nebius_api_key="bad", tavily_api_key="tvly-x"),
        httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(LLMClientError) as excinfo:
        client.chat([{"role": "user", "content": "hi"}], CHEAP, max_tokens=5)

    assert "401" in str(excinfo.value)
    assert len(requests) == 1


def test_empty_choices_is_an_error() -> None:
    client = LLMClient(
        _settings(cap=2.0),
        httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"choices": [], "usage": {}})
            )
        ),
    )

    with pytest.raises(LLMClientError, match="no choices"):
        client.chat([{"role": "user", "content": "hi"}], CHEAP, max_tokens=5)


def test_default_max_tokens_comes_from_tier() -> None:
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return _success()

    client = LLMClient(
        _settings(cap=2.0),
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    client.chat([{"role": "user", "content": "hi"}], CHEAP)

    assert bodies[0]["max_tokens"] == CHEAP.max_tokens
