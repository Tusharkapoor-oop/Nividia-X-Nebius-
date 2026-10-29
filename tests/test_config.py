"""Unit tests for configuration loading (lenient for doctor, strict for run)."""

from __future__ import annotations

from pathlib import Path

import pytest

from upgradepilot.config import ConfigError, Settings, repo_root


def test_settings_without_keys_key_state() -> None:
    settings = Settings(nebius_api_key="", tavily_api_key="x")
    assert settings.nebius_api_key == ""
    assert settings.tavily_api_key == "x"
    assert not settings.keys_configured


def test_settings_keys_stripped() -> None:
    settings = Settings(
        nebius_api_key="  abcd1234 ",
        tavily_api_key=" tvly-9988 ",
    )
    assert settings.nebius_api_key == "abcd1234"
    assert settings.tavily_api_key == "tvly-9988"
    assert settings.keys_configured


def test_require_keys_names_every_missing_key() -> None:
    settings = Settings(nebius_api_key="", tavily_api_key="")
    with pytest.raises(ConfigError, match="NEBIUS_API_KEY, TAVILY_API_KEY"):
        settings.require_keys()


def test_nim_mode_requires_nvidia_key_not_nebius() -> None:
    settings = Settings(
        llm_provider="nvidia-nim",
        nebius_api_key="nebius-key",
        nvidia_api_key="",
        tavily_api_key="tvly-x",
    )
    assert settings.active_key_name == "NVIDIA_API_KEY"
    with pytest.raises(ConfigError, match="NVIDIA_API_KEY"):
        settings.require_keys()


def test_active_key_follows_provider() -> None:
    tokenfactory = Settings(
        llm_provider="tokenfactory",
        nebius_api_key="nebius-key",
        nvidia_api_key="nvidia-key",
        tavily_api_key="tvly-x",
    )
    nim = tokenfactory.model_copy(update={"llm_provider": "nvidia-nim"})
    assert tokenfactory.active_api_key == "nebius-key"
    assert nim.active_api_key == "nvidia-key"
    assert tokenfactory.keys_configured and nim.keys_configured


def test_repo_root_is_project_root() -> None:
    # The checkout may be cloned under any directory name, so assert the
    # real invariants: pyproject.toml lives there and tests/ sits beneath it.
    root = repo_root()
    assert (root / "pyproject.toml").is_file()
    assert Path(__file__).resolve().parent.is_relative_to(root)
