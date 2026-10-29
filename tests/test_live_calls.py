"""Live integration tests: one real call per tier + one Tavily search.

Run only when the configured provider key and TAVILY_API_KEY exist:

    pytest -m live

The provider is whichever ``LLM_PROVIDER`` selects. Token Factory tiers are
priced from the live catalog; NVIDIA NIM tiers are unpriced and capped by
request count. NIM is a development path only — the hackathon submission must
run on Token Factory.

Spending on a full live marker invocation stays small because only tiny
prompts are sent. No model id, price, or context limit is hardcoded for the
Token Factory path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from upgradepilot.catalog import fetch_catalog
from upgradepilot.config import Settings, repo_root
from upgradepilot.llm import LLMClient
from upgradepilot.research import TavilyClient
from upgradepilot.tiers import ModelTier, build_tiers

pytestmark = [pytest.mark.live]

ART_DIR = repo_root() / "artifacts" / "phase0" / "live_calls"


def _settings() -> Settings:
    settings = Settings()
    if not settings.active_api_key or not settings.tavily_api_key:
        pytest.skip("API keys not configured; add them to .env to run -m live")
    return settings


def _artifact_path(name: str) -> Path:
    ART_DIR.mkdir(parents=True, exist_ok=True)
    return ART_DIR / name


def _record(payload: dict[str, Any], path: Path) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


@pytest.fixture(scope="module")
def live_tiers() -> dict[str, ModelTier]:
    settings = _settings()
    if settings.llm_provider == "nvidia-nim":
        # NIM publishes no pricing catalog; tiers are unpriced by design.
        from upgradepilot.tiers import build_tiers_unpriced

        tiers = build_tiers_unpriced(settings)
        _record(
            {
                "provider": settings.llm_provider,
                "tiers": {role: tier.model_dump() for role, tier in tiers.items()},
                "cap": {"mode": "requests", "max_calls": settings.max_llm_calls_per_run},
            },
            _artifact_path("catalog_summary.json"),
        )
        return tiers
    catalog = fetch_catalog(settings)
    tiers = build_tiers(settings, catalog)
    _record(
        {
            "catalog_models": len(catalog.models),
            "nvidia_models": [
                {
                    "name": model.name,
                    "status": model.status,
                    "license": model.license.name,
                    "flavors": [flavor.model_id for flavor in model.flavors],
                }
                for model in catalog.nvidia_models()
            ],
            "tiers": {role: tier.model_dump() for role, tier in tiers.items()},
        },
        _artifact_path("catalog_summary.json"),
    )
    return tiers


@pytest.mark.parametrize("role", ["cheap", "default", "strong"])
def test_live_llm_call_per_tier(role: str, live_tiers: dict[str, ModelTier]) -> None:
    settings = _settings()
    tier = live_tiers[role]
    client = LLMClient(settings, sleep=lambda _delay: None)
    try:
        response = client.chat(
            [
                {"role": "system", "content": "You are a test probe. Answer concisely."},
                {"role": "user", "content": "Reply with exactly: OK"},
            ],
            tier,
            max_tokens=128,
            temperature=0.0,
        )
        # Connectivity probe. NIM requests disable thinking, so both providers
        # should return the probe token plus real usage.
        assert "OK" in response.content, "provider did not return the probe token"
        assert response.usage.total_tokens > 0, "provider returned zero usage"
        priced = settings.llm_provider == "tokenfactory" and tier.is_priced
        _record(
            {
                "provider": settings.llm_provider,
                "tier": role,
                "model_id": tier.model_id,
                "priced": priced,
                "request": {
                    "messages": [
                        {"role": "system", "content": "You are a test probe. Answer concisely."},
                        {"role": "user", "content": "Reply with exactly: OK"},
                    ],
                    "max_tokens": 128,
                    "temperature": 0.0,
                },
                "raw_response": response.raw,
                "usage": response.usage.model_dump(),
                "finish_reason": response.finish_reason,
                "content_preview": response.content[:80],
                # USD cost only when the tier was priced; otherwise the run
                # ledger records unpriced token usage, never a fake dollar.
                "cost_usd": client.cost.total_cost_usd if priced else None,
                "unpriced_calls": None if priced else client.cost.unpriced_calls,
            },
            _artifact_path(
                f"{'tokenfactory' if settings.llm_provider == 'tokenfactory' else 'nvidia_nim'}_{role}.json"
            ),
        )
    finally:
        client.close()


def test_live_tavily_search() -> None:
    settings = _settings()
    client = TavilyClient(settings)
    try:
        result = client.search(
            "pydantic 2.0 migration guide breaking changes",
            max_results=3,
            search_depth="basic",
        )
        assert result.results, "expected at least one search result"
        _record(result.model_dump(), _artifact_path("tavily_search.json"))
    finally:
        client.close()
