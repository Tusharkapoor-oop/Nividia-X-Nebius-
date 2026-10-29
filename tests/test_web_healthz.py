"""Unit tests for the web /healthz endpoint (web extra optional in CI)."""

from __future__ import annotations

from upgradepilot import __version__

fastapi = pytest = None  # overwritten below


def test_healthz() -> None:
    pytest = __import__("pytest")
    fastapi = pytest.importorskip("fastapi")
    del fastapi

    from fastapi.testclient import TestClient

    from upgradepilot.web.app import create_app

    client = TestClient(create_app())
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
