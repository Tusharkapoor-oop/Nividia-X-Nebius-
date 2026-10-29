"""Parser and client for the public Token Factory model catalog.

The catalog endpoint ``GET https://tokenfactory.nebius.com/api/public/models_info``
returns a JSON **array** (top level) of model descriptors. Each descriptor
carries metadata plus a ``flavors`` list; pricing, context window, and the
concrete ``model_id`` usable at ``/v1/chat/completions`` live on the flavor.

Field names verified against the live catalog snapshots in
``artifacts/phase0/catalog/``.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from upgradepilot.config import Settings
from upgradepilot.retry import RetriesExhausted, request_with_retry

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class CatalogError(RuntimeError):
    """Raised when the catalog cannot be fetched or parsed."""


class LicenseInfo(BaseModel):
    """License block on a model descriptor."""

    model_config = ConfigDict(extra="ignore")

    name: str = ""
    type: str = ""
    url: str = ""


class ModelFlavor(BaseModel):
    """One deployment flavor of a model: the priced, callable unit."""

    model_config = ConfigDict(extra="ignore")

    model_id: str = Field(description="ID accepted by /v1/chat/completions.")
    label: str = ""  # observed "cheap" for all flavors; informational only
    context_window_k: int = 0
    max_model_len: int = 0
    input_price_per_million_tokens: float = 0.0
    output_price_per_million_tokens: float = 0.0
    quantization: str = ""
    tokens_per_second: float = 0.0
    external_provider: bool = False


class ModelInfo(BaseModel):
    """A model descriptor from the public catalog."""

    model_config = ConfigDict(extra="ignore")

    name: str
    vendor: str = ""
    status: str = ""
    type: str = ""
    description: str = ""
    license: LicenseInfo = Field(default_factory=LicenseInfo)
    huggingface_url: str = ""
    flavors: list[ModelFlavor] = Field(default_factory=list)


class Catalog(BaseModel):
    """Parsed catalog with lookup helpers."""

    models: list[ModelInfo]

    def nvidia_models(self) -> list[ModelInfo]:
        """Return descriptors whose vendor is NVIDIA."""
        return [m for m in self.models if m.vendor.lower() == "nvidia"]

    def find_model(self, name_substring: str) -> ModelInfo | None:
        """Return the first model whose name contains ``name_substring``."""
        needle = name_substring.lower()
        for model in self.models:
            if needle in model.name.lower():
                return model
        return None

    def find_flavor(self, model_id: str) -> ModelFlavor | None:
        """Locate the flavor matching a full model_id (case-insensitive)."""
        wanted = model_id.lower()
        for model in self.models:
            for flavor in model.flavors:
                if flavor.model_id.lower() == wanted:
                    return flavor
        return None

    def find_model_for_flavor(self, model_id: str) -> ModelInfo | None:
        """Return the model descriptor that owns ``model_id``."""
        wanted = model_id.lower()
        for model in self.models:
            if any(flavor.model_id.lower() == wanted for flavor in model.flavors):
                return model
        return None


def default_flavor(model: ModelInfo) -> ModelFlavor | None:
    """Pick a deterministic default flavor for a model.

    Preference: highest max_model_len, then cheapest input price, then the
    lexicographically smallest model_id. Returns None when the model has no
    flavor with a usable model_id.
    """
    usable = [flavor for flavor in model.flavors if flavor.model_id]
    if not usable:
        return None
    return sorted(
        usable,
        key=lambda flavor: (
            -flavor.max_model_len,
            flavor.input_price_per_million_tokens,
            flavor.model_id,
        ),
    )[0]


def parse_catalog(raw: Any) -> Catalog:
    """Parse the raw JSON payload from the catalog endpoint.

    Raises:
        CatalogError: if the payload is not a JSON array of valid entries.
    """
    if not isinstance(raw, list):
        raise CatalogError(f"Expected catalog to be a JSON array, got {type(raw).__name__}")

    models: list[ModelInfo] = []
    errors: list[str] = []
    for index, entry in enumerate(raw):
        try:
            models.append(ModelInfo.model_validate(entry))
        except ValidationError as exc:
            errors.append(
                f"entry[{index}] "
                f"({entry.get('name', '?') if isinstance(entry, dict) else '?'}): "
                f"{exc.error_count()} validation error(s)"
            )
            logger.warning("Skipping unparseable catalog entry %d: %s", index, exc)

    if not models:
        raise CatalogError(
            "No catalog entries parsed successfully. First errors: " + "; ".join(errors[:3])
        )
    if errors:
        logger.info(
            "Parsed %d/%d catalog entries (%d skipped)",
            len(models),
            len(raw),
            len(errors),
        )
    return Catalog(models=models)


def fetch_catalog(
    settings: Settings,
    http_client: httpx.Client | None = None,
    *,
    sleep: Callable[[float], None] | None = None,
) -> Catalog:
    """Fetch and parse the live catalog with retry/backoff.

    Args:
        settings: Supplies ``tokenfactory_catalog_url``.
        http_client: Injectable client for tests; a client is created and
            closed when omitted.
        sleep: Injectable retry sleep for tests.

    Raises:
        CatalogError: on transport failure, non-200 status, invalid JSON, or
            an unparseable payload.
    """
    client = http_client or httpx.Client(timeout=30.0)
    owns_client = http_client is None
    try:
        try:
            response = request_with_retry(
                lambda: client.get(settings.tokenfactory_catalog_url),
                retryable_status=_RETRYABLE_STATUS,
                sleep=sleep if sleep is not None else time.sleep,
            )
        except RetriesExhausted as exc:
            raise CatalogError(
                f"Catalog fetch failed after retries: {settings.tokenfactory_catalog_url}"
            ) from exc
        except httpx.HTTPError as exc:
            raise CatalogError(
                f"Catalog fetch failed: {settings.tokenfactory_catalog_url}: {exc}"
            ) from exc

        if response.status_code != 200:
            raise CatalogError(
                f"Catalog returned HTTP {response.status_code}: "
                f"{settings.tokenfactory_catalog_url}"
            )
        try:
            raw = response.json()
        except ValueError as exc:
            raise CatalogError("Catalog returned a non-JSON body.") from exc
        return parse_catalog(raw)
    finally:
        if owns_client:
            client.close()
