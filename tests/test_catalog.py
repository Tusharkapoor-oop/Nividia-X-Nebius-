"""Unit tests for the catalog parser, fetcher, and tier mapping.

The fixture is trimmed to the five NVIDIA models but is raw bytes copied
from the live endpoint, not hand-written, so field-name drift is caught.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from upgradepilot.catalog import (
    Catalog,
    CatalogError,
    default_flavor,
    fetch_catalog,
    parse_catalog,
)
from upgradepilot.config import Settings
from upgradepilot.tiers import TierConfigError, build_tiers

FIXTURE = Path(__file__).parent / "fixtures" / "catalog_nvidia.json"

EXPECTED_TIERS = {
    "cheap": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
    "default": "nvidia/Nemotron-3_5-Lightning",
    "strong": "nvidia/Nemotron-3-Ultra-550b-a55b",
}


def _fixture_raw() -> list[dict[str, Any]]:
    raw: list[dict[str, Any]] = json.loads(FIXTURE.read_text(encoding="utf-8-sig"))
    return raw


@pytest.fixture(scope="module")
def catalog() -> Catalog:
    return parse_catalog(_fixture_raw())


def test_parse_counts_nvidia_models(catalog: Catalog) -> None:
    assert len(catalog.models) == 5
    assert len(catalog.nvidia_models()) == 5


def test_tier_model_ids_resolve(catalog: Catalog) -> None:
    for model_id in EXPECTED_TIERS.values():
        flavor = catalog.find_flavor(model_id)
        assert flavor is not None, model_id
        assert flavor.model_id == model_id


def test_tier_pricing_and_context_from_catalog(catalog: Catalog) -> None:
    cheap = catalog.find_flavor(EXPECTED_TIERS["cheap"])
    default = catalog.find_flavor(EXPECTED_TIERS["default"])
    strong = catalog.find_flavor(EXPECTED_TIERS["strong"])
    assert cheap is not None
    assert default is not None
    assert strong is not None

    assert cheap.input_price_per_million_tokens == 0.06
    assert cheap.output_price_per_million_tokens == 0.24
    assert cheap.max_model_len == 262144

    assert default.input_price_per_million_tokens == 0.06
    assert default.output_price_per_million_tokens == 0.24
    assert default.max_model_len == 1048576

    assert strong.input_price_per_million_tokens == 1.0
    assert strong.output_price_per_million_tokens == 3.0
    assert strong.max_model_len == 1048576


def test_config_defaults_match_verified_tiers() -> None:
    settings = Settings()
    assert settings.model_tier_cheap == EXPECTED_TIERS["cheap"]
    assert settings.model_tier_default == EXPECTED_TIERS["default"]
    assert settings.model_tier_strong == EXPECTED_TIERS["strong"]


def test_build_tiers_uses_live_catalog_prices(catalog: Catalog) -> None:
    tiers = build_tiers(Settings(), catalog)
    assert set(tiers) == {"cheap", "default", "strong"}

    assert tiers["cheap"].model_id == EXPECTED_TIERS["cheap"]
    assert tiers["cheap"].input_price_per_m == 0.06
    assert tiers["cheap"].context_window == 262144

    assert tiers["default"].input_price_per_m == 0.06
    assert tiers["default"].context_window == 1048576

    assert tiers["strong"].output_price_per_m == 3.0
    assert tiers["strong"].context_window == 1048576


def test_missing_model_id_raises(catalog: Catalog) -> None:
    settings = Settings(model_tier_strong="nvidia/nonexistent-model")
    with pytest.raises(TierConfigError, match="not in the live"):
        build_tiers(settings, catalog)


def test_fetch_catalog_retries_then_parses() -> None:
    raw = _fixture_raw()
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, text="temporary")
        return httpx.Response(200, json=raw)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    parsed = fetch_catalog(Settings(), client, sleep=lambda _delay: None)
    assert calls["n"] == 2
    assert len(parsed.models) == 5


def test_fetch_catalog_exhaustion_is_typed() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, text="down")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(CatalogError, match="after retries"):
        fetch_catalog(Settings(), client, sleep=lambda _delay: None)
    assert calls["n"] == 4


def test_parse_catalog_rejects_non_array() -> None:
    with pytest.raises(CatalogError, match="JSON array"):
        parse_catalog({"models": []})


def test_parse_catalog_all_entries_broken_raises() -> None:
    raw = [{"no_name_here": True}, {"also": "bad"}]
    with pytest.raises(CatalogError, match="No catalog entries"):
        parse_catalog(raw)


def test_default_flavor_prefers_largest_context() -> None:
    catalog = parse_catalog(_fixture_raw())
    model = catalog.find_model("Nemotron-3-Ultra")
    assert model is not None
    flavor = default_flavor(model)
    assert flavor is not None
    assert flavor.model_id == EXPECTED_TIERS["strong"]
