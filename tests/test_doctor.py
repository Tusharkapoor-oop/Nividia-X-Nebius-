"""Unit tests for doctor checks without live API calls or network access."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from upgradepilot import cli
from upgradepilot.catalog import Catalog, CatalogError, parse_catalog
from upgradepilot.config import Settings

FIXTURE = Path(__file__).parent / "fixtures" / "catalog_nvidia.json"


def _catalog() -> Catalog:
    raw: list[dict[str, Any]] = json.loads(FIXTURE.read_text(encoding="utf-8-sig"))
    return parse_catalog(raw)


def test_doctor_checks_offline_structure(monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = _catalog()
    monkeypatch.setattr(cli, "fetch_catalog", lambda _settings: catalog)

    # Keys are forced empty so this test stays offline even when a developer's
    # real .env is present (it must never make billable calls).
    settings = Settings(nebius_api_key="", nvidia_api_key="", tavily_api_key="")
    checks = {c["check"]: c for c in cli._doctor_checks(settings)}

    assert checks["python>=3.11"]["ok"] is True
    assert checks["git"]["ok"] is True
    assert checks["keys"]["ok"] is False
    assert checks["tokenfactory catalog"]["ok"] is True
    assert checks["tier mapping"]["ok"] is True
    assert "$0.06/M" in checks["tier mapping"]["detail"]
    assert checks["tokenfactory chat"]["detail"] == "skipped (no key)"
    assert checks["tavily search"]["detail"] == "skipped (no key)"


def test_doctor_reports_catalog_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(_settings: Settings) -> Catalog:
        raise CatalogError("catalog is down")

    monkeypatch.setattr(cli, "fetch_catalog", fail)
    settings = Settings(nebius_api_key="", nvidia_api_key="", tavily_api_key="")
    checks = {c["check"]: c for c in cli._doctor_checks(settings)}

    assert checks["tokenfactory catalog"]["ok"] is False
    assert "catalog is down" in checks["tokenfactory catalog"]["detail"]
    assert "tier mapping" not in checks
