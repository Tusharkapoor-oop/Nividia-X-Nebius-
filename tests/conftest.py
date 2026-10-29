"""Test isolation from a developer's local .env.

Offline tests must be deterministic regardless of which provider the local
``.env`` selects. Live tests (``-m live``) are exempt so they can exercise the
configured real provider.

Environment variables outrank values in ``.env`` in pydantic-settings, so the
fixture pins the Token Factory defaults for offline tests and blanks the keys.
"""

from __future__ import annotations

import pytest

_TOKENFACTORY_DEFAULTS = {
    "LLM_PROVIDER": "tokenfactory",
    "MODEL_TIER_CHEAP": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
    "MODEL_TIER_DEFAULT": "nvidia/Nemotron-3_5-Lightning",
    "MODEL_TIER_STRONG": "nvidia/Nemotron-3-Ultra-550b-a55b",
    "NEBIUS_API_KEY": "",
    "NVIDIA_API_KEY": "",
    "TAVILY_API_KEY": "",
}


@pytest.fixture(autouse=True)
def _offline_settings_defaults(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    if request.node.get_closest_marker("live") is not None:
        return
    for name, value in _TOKENFACTORY_DEFAULTS.items():
        monkeypatch.setenv(name, value)
