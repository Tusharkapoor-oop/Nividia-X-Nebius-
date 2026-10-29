"""Unit tests for the Tavily search client (no network)."""

from __future__ import annotations

import httpx
import pytest

from upgradepilot.config import Settings
from upgradepilot.research import TavilyClient, TavilyError


def _settings() -> Settings:
    return Settings(
        nebius_api_key="nab",
        tavily_api_key="tvly-test",
    )


def test_search_uses_bearer_header() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization", "")
        return httpx.Response(
            200,
            json={
                "query": "q",
                "answer": "ans",
                "results": [
                    {"title": "T1", "url": "u1", "content": "c1", "score": 0.9},
                ],
                "usage": {"credits": 1},
                "response_time": 0.3,
            },
        )

    client = TavilyClient(_settings(), httpx.Client(transport=httpx.MockTransport(handler)))
    result = client.search("pydantic 2.0 migration guide", max_results=1)

    assert seen["auth"] == "Bearer tvly-test"
    assert result.answer == "ans"
    assert result.results[0].title == "T1"
    assert result.credits_used == 1
    assert "T1" in result.summary()


def test_429_retries_and_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"query": "q", "results": [], "usage": {"credits": 1}})

    client = TavilyClient(_settings(), httpx.Client(transport=httpx.MockTransport(handler)))
    result = client.search("two-failures")
    assert calls["n"] == 3
    assert result.results == []


def test_plan_limit_432_clear_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(432, json={"detail": {"error": "Key limit exceeded"}})

    client = TavilyClient(_settings(), httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(TavilyError, match="plan/pay-as-you-go limit"):
        client.search("limited", max_results=1)


def test_401_clear_error_no_retry() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"detail": {"error": "bad key"}})

    client = TavilyClient(_settings(), httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(TavilyError, match="401"):
        client.search("noauth", max_results=1)
    assert calls["n"] == 1
