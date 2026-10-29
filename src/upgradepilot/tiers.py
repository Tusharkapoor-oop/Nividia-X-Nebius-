"""Model tiers priced from the live Token Factory catalog.

Model *choice* is policy (configured via environment variables); prices and
context limits are never copied from memory. :func:`build_tiers` requires a
catalog fetched from the public Token Factory endpoint in the same process,
so a run cannot be priced against a stale table.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from upgradepilot.catalog import Catalog
from upgradepilot.config import Settings

TierRole = Literal["cheap", "default", "strong"]

# A conservative, uniform completion budget. The exact per-request parameter
# is sent to the API and recorded with each call.
DEFAULT_MAX_TOKENS = 4096


class TierConfigError(RuntimeError):
    """A configured tier model is missing, inactive, or unpriced in the catalog."""


class ModelTier(BaseModel):
    """A run role whose parameters come from the live catalog when possible.

    Prices and context are ``None`` for providers that publish no machine
    catalog (nvidia-nim); ``is_priced`` must be checked before any USD math.
    """

    role: TierRole
    model_id: str
    max_tokens: int = Field(gt=0)
    context_window: int | None = Field(default=None, gt=0)
    input_price_per_m: float | None = Field(default=None, ge=0)
    output_price_per_m: float | None = Field(default=None, ge=0)

    @property
    def is_priced(self) -> bool:
        """True when both per-million prices came from a live catalog."""
        return self.input_price_per_m is not None and self.output_price_per_m is not None


def _configured_model_id(role: TierRole, settings: Settings) -> str:
    if role == "cheap":
        return settings.model_tier_cheap
    if role == "default":
        return settings.model_tier_default
    return settings.model_tier_strong


def build_tier(role: TierRole, settings: Settings, catalog: Catalog) -> ModelTier:
    """Build one tier using the live catalog's price and context limit.

    Raises:
        TierConfigError: when the configured model is absent, inactive, or
            has no usable context/pricing data.
    """
    model_id = _configured_model_id(role, settings)
    model = catalog.find_model_for_flavor(model_id)
    if model is None:
        raise TierConfigError(
            f"tier {role!r}: model_id {model_id!r} is not in the live Token Factory catalog"
        )
    if model.status.lower() != "active":
        raise TierConfigError(
            f"tier {role!r}: model_id {model_id!r} has catalog status {model.status!r}"
        )

    flavor = catalog.find_flavor(model_id)
    if flavor is None:
        raise TierConfigError(f"tier {role!r}: no flavor for {model_id!r}")
    if flavor.max_model_len <= 0:
        raise TierConfigError(
            f"tier {role!r}: {model_id!r} has no usable context limit in the catalog"
        )
    return ModelTier(
        role=role,
        model_id=model_id,
        max_tokens=DEFAULT_MAX_TOKENS,
        context_window=flavor.max_model_len,
        input_price_per_m=flavor.input_price_per_million_tokens,
        output_price_per_m=flavor.output_price_per_million_tokens,
    )


def build_tiers(settings: Settings, catalog: Catalog) -> dict[str, ModelTier]:
    """Build all three tiers from one freshly fetched catalog."""
    return {
        "cheap": build_tier("cheap", settings, catalog),
        "default": build_tier("default", settings, catalog),
        "strong": build_tier("strong", settings, catalog),
    }


def build_tiers_unpriced(settings: Settings) -> dict[str, ModelTier]:
    """NIM-mode tiers: model ids from configuration, no pricing available.

    The provider publishes no machine-readable pricing/context catalog, so
    dollar figures would be invented. Cost caps for these tiers are enforced
    by request count in ``llm.LLMClient`` instead.
    """
    tiers: dict[str, ModelTier] = {}
    for role in ("cheap", "default", "strong"):
        model_id = _configured_model_id(role, settings)
        if not model_id:
            raise TierConfigError(f"tier {role!r}: no model id configured")
        tiers[role] = ModelTier(
            role=role,
            model_id=model_id,
            max_tokens=DEFAULT_MAX_TOKENS,
        )
    return tiers
