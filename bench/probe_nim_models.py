"""Free probe: list Nemotron model ids on NVIDIA NIM via GET /v1/models.

Reads the key from .env but NEVER prints it; prints only model ids and
verdicts for the configured tier ids. No chat tokens are billed for this.

Usage: python bench/probe_nim_models.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx


def _env(name: str) -> str:
    for raw in (Path(".env")).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith(f"{name}="):
            value = line.split("=", 1)[1].strip()
            return value.strip('"').strip("'")
        if line.startswith(f"export {name}="):
            value = line.split("=", 1)[1].strip()
            return value.strip('"').strip("'")
    return os.environ.get(name, "")


def main() -> int:
    key = _env("NVIDIA_API_KEY")
    if not key:
        print("NVIDIA_API_KEY not set in .env — cannot probe.")
        return 1
    base = _env("NVIDIA_NIM_BASE_URL") or "https://integrate.api.nvidia.com/v1"
    if "TOKENFACTORY_BASE_URL" in os.environ and not _env("NVIDIA_NIM_BASE_URL"):
        base = "https://integrate.api.nvidia.com/v1"

    url = f"{base.rstrip('/')}/models"
    response = httpx.get(url, headers={"Authorization": f"Bearer {key}"}, timeout=30.0)
    print(f"GET {url} -> HTTP {response.status_code}")
    if response.status_code != 200:
        print("body head:", response.text[:300])
        return 1
    data = response.json()
    items = data.get("data", []) if isinstance(data, dict) else data
    ids = [str(item.get("id", "")) for item in items if isinstance(item, dict)]
    nemotron_ids = sorted(i for i in ids if "nemotron" in i.lower())
    print(f"total models listed: {len(ids)}; nemotron ids: {len(nemotron_ids)}")

    want = {
        "cheap": _env("MODEL_TIER_CHEAP") or "",
        "default": _env("MODEL_TIER_DEFAULT") or "",
        "strong": _env("MODEL_TIER_STRONG") or "",
    }
    for role in ("cheap", "default", "strong"):
        model_id = want[role]
        present = model_id in ids
        print(f"tier {role}: configured={model_id!r} present_on_nim={present}")

    print("--- nemotron ids on NIM ---")
    for model_id in nemotron_ids:
        print(" ", model_id)
    if "--json" in sys.argv:
        Path("artifacts/phase0/live_calls/nim_models_probe.json").parent.mkdir(
            parents=True, exist_ok=True
        )
        Path("artifacts/phase0/live_calls/nim_models_probe.json").write_text(
            json.dumps(
                {
                    "url": url,
                    "status": response.status_code,
                    "count": len(ids),
                    "nemotron_ids": nemotron_ids,
                    "tiers": want,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print("saved artifacts/phase0/live_calls/nim_models_probe.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
