"""Unit tests for the nvidia-nim provider mode (all offline).

NIM publishes no pricing catalog, so these tests pin the honesty rules:
- tiers are built without prices and are never USD-costed;
- the request-count cap blocks *before* any network request;
- unpriced calls are recorded as unpriced, not converted to fake dollars.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from upgradepilot.config import Settings
from upgradepilot.llm import LLMClient, SpendingCapExceeded, call_cost
from upgradepilot.tiers import ModelTier, build_tiers_unpriced


def _nim_settings(max_calls: int = 3) -> Settings:
    return Settings(
        nebius_api_key="",
        nvidia_api_key="nvapi-test",
        tavily_api_key="tvly-x",
        llm_provider="nvidia-nim",
        max_llm_calls_per_run=max_calls,
    )


def _unpriced_tier(model_id: str = "nvidia/nemotron-3-ultra-550b-a55b") -> ModelTier:
    return ModelTier(role="default", model_id=model_id, max_tokens=16)


SUCCEED_RESPONSE = {
    "model": "nvidia/nemotron-3-ultra-550b-a55b",
    "choices": [{"message": {"content": "OK!"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
}


def test_nim_tiers_have_no_prices() -> None:
    settings = _nim_settings()
    settings = settings.model_copy(
        update={
            "model_tier_cheap": "a/cheap",
            "model_tier_default": "b/default",
            "model_tier_strong": "c/strong",
        }
    )
    tiers = build_tiers_unpriced(settings)
    assert set(tiers) == {"cheap", "default", "strong"}
    for tier in tiers.values():
        assert not tier.is_priced
        assert tier.input_price_per_m is None
        assert tier.output_price_per_m is None
        assert tier.context_window is None


def test_call_cost_refuses_unpriced_tier() -> None:
    from upgradepilot.llm import LLMClientError
    from upgradepilot.models import TokenUsage

    with pytest.raises(LLMClientError):
        call_cost(TokenUsage(prompt_tokens=10, completion_tokens=10), _unpriced_tier())


def test_request_cap_blocks_before_network() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=SUCCEED_RESPONSE)

    client = LLMClient(
        _nim_settings(max_calls=2),
        httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _delay: None,
    )
    tier = _unpriced_tier()
    for _ in range(2):
        response = client.chat([{"role": "user", "content": "hi"}], tier)
        assert response.content == "OK!"
    with pytest.raises(SpendingCapExceeded, match="request cap"):
        client.chat([{"role": "user", "content": "third"}], tier)
    assert len(requests) == 2  # third call was blocked before any HTTP
    client.close()


def test_nim_uses_nvidia_key_and_endpoint() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization", "")
        seen["url"] = str(request.url)
        seen["body"] = request.content.decode("utf-8")
        return httpx.Response(200, json=SUCCEED_RESPONSE)

    client = LLMClient(
        _nim_settings(),
        httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _delay: None,
    )
    try:
        client.chat([{"role": "user", "content": "hi"}], _unpriced_tier())
    finally:
        client.close()
    assert seen["auth"] == "Bearer nvapi-test"
    assert seen["url"].startswith("https://integrate.api.nvidia.com/v1/")
    sent = json.loads(seen["body"])
    assert sent["chat_template_kwargs"] == {"enable_thinking": False}


def test_tokenfactory_payload_has_no_nim_thinking_flag() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json=SUCCEED_RESPONSE)

    tier = ModelTier(
        role="cheap",
        model_id="nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
        max_tokens=16,
        context_window=262144,
        input_price_per_m=0.06,
        output_price_per_m=0.24,
    )
    settings = Settings(
        nebius_api_key="nab-test",
        tavily_api_key="tvly-x",
        llm_provider="tokenfactory",
    )
    client = LLMClient(
        settings,
        httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _delay: None,
    )
    try:
        client.chat([{"role": "user", "content": "hi"}], tier)
    finally:
        client.close()
    assert "chat_template_kwargs" not in seen["body"]


def test_unpriced_calls_are_not_dollarized() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=SUCCEED_RESPONSE)

    client = LLMClient(
        _nim_settings(max_calls=5),
        httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _delay: None,
    )
    try:
        client.chat([{"role": "user", "content": "hi"}], _unpriced_tier())
    finally:
        client.close()
    assert client.cost.calls == 1
    assert client.cost.unpriced_calls == 1
    assert client.cost.total_cost_usd == 0.0  # never invented
    assert client.cost.fully_priced is False


def test_nim_never_dollarizes_even_with_a_priced_tier() -> None:
    """A caller's stray catalog prices must not override provider honesty."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=SUCCEED_RESPONSE)

    priced_tier = ModelTier(
        role="default",
        model_id="nvidia/nemotron-3-ultra-550b-a55b",
        max_tokens=16,
        context_window=1048576,
        input_price_per_m=1.0,
        output_price_per_m=3.0,
    )
    client = LLMClient(
        _nim_settings(max_calls=5),
        httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _delay: None,
    )
    try:
        client.chat([{"role": "user", "content": "hi"}], priced_tier)
    finally:
        client.close()
    assert client.cost.total_cost_usd == 0.0
    assert client.cost.unpriced_calls == 1
    assert client.cost.fully_priced is False


def test_tokenfactory_mode_still_usd_caps() -> None:
    """The default provider keeps its USD preflight cap; request cap unused."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=SUCCEED_RESPONSE)

    settings = Settings(
        nebius_api_key="nab-test",
        tavily_api_key="tvly-x",
        # Settings enforces cap >= 0.01, so a tiny call is projected under the
        # cap on purpose; the heavy projection below must still be blocked.
        token_cost_cap_usd=0.01,
    )
    priced_tier = ModelTier(
        role="cheap",
        model_id="nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
        max_tokens=4096,
        context_window=262144,
        input_price_per_m=1.0,
        output_price_per_m=3.0,
    )
    client = LLMClient(
        settings,
        httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _delay: None,
    )
    try:
        with pytest.raises(SpendingCapExceeded):
            client.chat([{"role": "user", "content": "prompt " * 50}], priced_tier)
        assert requests == []
        assert settings.llm_provider == "tokenfactory"
        assert settings.tokenfactory_base_url.startswith("https://api.tokenfactory.nebius.com")
    finally:
        client.close()
