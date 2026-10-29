"""Application configuration loaded from environment variables.

Uses pydantic-settings for validation. All secrets come from a .env file
(git-ignored) or the process environment. Keys are optional at import time
so that ``upgradepilot doctor`` can diagnose an unconfigured environment;
running an actual upgrade requires keys via :meth:`Settings.require_keys`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root = two parent directories above src/upgradepilot/config.py.
_REPO_ROOT = Path(__file__).resolve().parents[2]


class ConfigError(RuntimeError):
    """Raised when configuration is too incomplete to run the pipeline."""


class Settings(BaseSettings):
    """Validated runtime configuration for UpgradePilot.

    Empty API keys are allowed so ``doctor`` can describe an unconfigured
    environment; per-run entry points must call :meth:`require_keys`.
    """

    model_config = SettingsConfigDict(
        env_file=str(_REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Secrets (empty = not configured) ──────────────────────────────
    nebius_api_key: str = Field(
        default="",
        description="Nebius Token Factory API key (used when llm_provider=tokenfactory).",
    )
    nvidia_api_key: str = Field(
        default="",
        description="NVIDIA NIM / build.nvidia.com key (used when llm_provider=nvidia-nim).",
    )
    tavily_api_key: str = Field(
        default="",
        description="Tavily search API key.",
    )

    # ── LLM provider ─────────────────────────────────────────────────
    llm_provider: Literal["tokenfactory", "nvidia-nim"] = Field(
        default="tokenfactory",
        description="tokenfactory = Nebius Token Factory (catalog-priced, "
        "USD-capped). nvidia-nim = build.nvidia.com API (no public pricing "
        "catalog; capped by request count + output tokens instead of USD).",
    )
    tokenfactory_base_url: str = Field(
        default="https://api.tokenfactory.nebius.com/v1",
        description="OpenAI-compatible base URL for Token Factory.",
    )
    nvidia_nim_base_url: str = Field(
        default="https://integrate.api.nvidia.com/v1",
        description="OpenAI-compatible base URL for NVIDIA NIM / build.nvidia.com.",
    )
    tokenfactory_catalog_url: str = Field(
        default="https://tokenfactory.nebius.com/api/public/models_info",
        description="Public model catalog endpoint (Token Factory only).",
    )

    # ── Model tier IDs (verified against live catalog 2026-10-19) ─────
    model_tier_cheap: str = Field(
        default="nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
        description="Cheapest Nemotron model for triage.",
    )
    model_tier_default: str = Field(
        default="nvidia/Nemotron-3_5-Lightning",
        description="Default Nemotron model for patch generation.",
    )
    model_tier_strong: str = Field(
        default="nvidia/Nemotron-3-Ultra-550b-a55b",
        description="Strongest Nemotron model for escalation.",
    )

    # ── Spending & safety ─────────────────────────────────────────────
    token_cost_cap_usd: float = Field(
        default=2.0,
        ge=0.01,
        description="Hard spending cap per run (USD). Token Factory calls "
        "are preflighted against live catalog prices.",
    )
    max_llm_calls_per_run: int = Field(
        default=12,
        ge=1,
        description="Hard cap on chat calls per run when the provider has no "
        "pricing catalog (nvidia-nim). USD cap does not apply there; never "
        "fabricate a dollar figure for it.",
    )
    max_iterations: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum patch-verify iterations before giving up.",
    )
    escalate_after: int = Field(
        default=2,
        ge=1,
        description="Switch to strong tier after this many failed iterations.",
    )
    pytest_timeout_seconds: int = Field(
        default=300,
        ge=10,
        description="Timeout for a single pytest invocation (seconds).",
    )

    # ── Logging ───────────────────────────────────────────────────────
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
    )

    @field_validator("nebius_api_key", "nvidia_api_key", "tavily_api_key")
    @classmethod
    def _strip_keys(cls, value: str, _info: ValidationInfo) -> str:
        return value.strip()

    @property
    def active_api_key(self) -> str:
        """Key for the configured provider (never mixes provider credentials)."""
        if self.llm_provider == "nvidia-nim":
            return self.nvidia_api_key
        return self.nebius_api_key

    @property
    def active_key_name(self) -> str:
        """Environment variable name for the configured provider's key."""
        if self.llm_provider == "nvidia-nim":
            return "NVIDIA_API_KEY"
        return "NEBIUS_API_KEY"

    @property
    def keys_configured(self) -> bool:
        """True when the active provider key and Tavily key are present."""
        return bool(self.active_api_key) and bool(self.tavily_api_key)

    def require_keys(self) -> None:
        """Raise ConfigError unless the active provider key and Tavily key exist."""
        missing: list[str] = []
        if not self.active_api_key:
            missing.append(self.active_key_name)
        if not self.tavily_api_key:
            missing.append("TAVILY_API_KEY")
        if missing:
            env_path = _REPO_ROOT / ".env"
            raise ConfigError(
                "Missing required API keys for llm_provider="
                f"{self.llm_provider}: "
                + ", ".join(missing)
                + f". Copy .env.example to {env_path} and fill them in."
            )


def load_settings() -> Settings:
    """Load settings; keys may be absent (doctor-safe)."""
    return Settings()


def load_settings_for_run() -> Settings:
    """Load settings and fail fast if API keys are missing."""
    settings = load_settings()
    settings.require_keys()
    return settings


def repo_root() -> Path:
    """Absolute path of the UpgradePilot repository root."""
    return _REPO_ROOT
