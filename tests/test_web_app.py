"""Phase 6 web app tests: UI, JSON API, SSE streaming, and run triggering.

The heavy machinery (prepare_target, run_upgrade) is faked so these tests
exercise the web layer's real behavior — HTTP status codes, SSE framing,
artifact reads, busy-run handling — without cloning repos, building venvs,
or spending API budget.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from upgradepilot.agent import UpgradeReport, UpgradeRequest, proof_card_markdown
from upgradepilot.config import ConfigError, Settings
from upgradepilot.harness import RepoWorkdir, VenvInfo
from upgradepilot.prepare import PreparedTarget
from upgradepilot.run_ledger import RunLedger
from upgradepilot.verify import VerifyStatus
from upgradepilot.web.app import create_app
from upgradepilot.web.runs import RunController

GREEN_REPORT = UpgradeReport(
    run_id="run-test-000000-abcdef",
    request=UpgradeRequest(repo="/tmp/demo", package="pydantic", to_version="2.9.0"),
    status=VerifyStatus.GREEN,
    iterations_used=2,
)


def _make_app(tmp_path: Path) -> FastAPI:
    return create_app(
        artifacts_dir=tmp_path / "runs",
        bench_dir=tmp_path / "bench",
        bench_artifacts=tmp_path / "phase2",
    )


def _seed_run(artifacts_root: Path, run_id: str = "run-20261025T000000-aaaaaa") -> Path:
    run_dir = artifacts_root / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "upgrade_report.json").write_text(
        GREEN_REPORT.model_dump_json(indent=2), encoding="utf-8"
    )
    (run_dir / "proof_card.md").write_text(proof_card_markdown(GREEN_REPORT), encoding="utf-8")
    return run_dir


def _wait_idle(controller: RunController, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while controller.active_run_id is not None and time.monotonic() < deadline:
        time.sleep(0.02)
    assert controller.active_run_id is None, "run did not finish in time"


def _read_sse(client: TestClient, run_id: str, timeout: float = 10.0) -> list[str]:
    """Collect SSE lines until the stream closes, with a time guard."""
    lines: list[str] = []
    with client.stream("GET", f"/api/runs/{run_id}/events", timeout=timeout) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        for line in response.iter_lines():
            lines.append(line)
            if line.startswith("event: done"):
                break
    return lines


# -- UI ---------------------------------------------------------------------


def test_index_serves_accessible_ui(tmp_path: Path) -> None:
    client = TestClient(_make_app(tmp_path))
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    body = resp.text
    assert "<main" in body
    assert "UpgradePilot" in body
    assert "skip-link" in body
    assert "/static/app.js" in body
    # form controls are labelled
    assert 'for="repo"' in body
    assert 'for="package"' in body


def test_static_assets_are_served(tmp_path: Path) -> None:
    client = TestClient(_make_app(tmp_path))
    for path in ("/static/app.js", "/static/styles.css"):
        resp = client.get(path)
        assert resp.status_code == 200, path


def test_healthz_contract_unchanged(tmp_path: Path) -> None:
    client = TestClient(_make_app(tmp_path))
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# -- read API ---------------------------------------------------------------


def test_api_runs_empty_when_no_artifacts(tmp_path: Path) -> None:
    client = TestClient(_make_app(tmp_path))
    resp = client.get("/api/runs")
    assert resp.status_code == 200
    assert resp.json() == []


def test_api_runs_lists_seeded_run(tmp_path: Path) -> None:
    _seed_run(tmp_path / "runs")
    client = TestClient(_make_app(tmp_path))
    runs = client.get("/api/runs").json()
    assert len(runs) == 1
    run = runs[0]
    assert run["status"] == "GREEN"
    assert run["package"] == "pydantic"
    assert run["to_version"] == "2.9.0"
    assert run["iterations"] == 2
    assert run["guard_clean"] is True
    assert run["active"] is False


def test_api_run_detail_returns_report_and_proof_card(tmp_path: Path) -> None:
    run_id = "run-20261025T000000-bbbbbb"
    _seed_run(tmp_path / "runs", run_id)
    client = TestClient(_make_app(tmp_path))
    resp = client.get(f"/api/runs/{run_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == run_id
    assert body["report"]["status"] == "GREEN"
    assert body["proof_card"]
    assert "GREEN" in body["proof_card"]
    assert body["error"] is None


def test_api_run_detail_missing_run_returns_no_report(tmp_path: Path) -> None:
    client = TestClient(_make_app(tmp_path))
    resp = client.get("/api/runs/run-does-not-exist")
    assert resp.status_code == 200
    assert resp.json()["report"] is None
    assert resp.json()["proof_card"] is None


def test_api_rejects_unsafe_run_id(tmp_path: Path) -> None:
    client = TestClient(_make_app(tmp_path))
    resp = client.get("/api/runs/bad%20id")
    assert resp.status_code == 404
    resp = client.get("/api/runs/bad%20id/events")
    assert resp.status_code == 404


# -- SSE --------------------------------------------------------------------


def test_sse_replays_recorded_events_then_ends(tmp_path: Path) -> None:
    run_id = "run-20261025T000000-cccccc"
    run_dir = _seed_run(tmp_path / "runs", run_id)
    ledger = RunLedger(run_dir)
    ledger.append("setup", run_id=run_id, package="pydantic")
    ledger.append("verify_1", status="ok", detail="baseline GREEN")

    client = TestClient(_make_app(tmp_path))
    lines = _read_sse(client, run_id)

    joined = "\n".join(lines)
    assert '"event":"setup"' in joined
    assert '"event":"verify_1"' in joined
    assert "baseline GREEN" in joined
    assert any(line.startswith("event: done") for line in lines)


# -- starting a run ---------------------------------------------------------


def _fake_settings() -> Settings:
    return Settings(nebius_api_key="mock", tavily_api_key="mock")


def _fake_prepare(
    source: Path,
    artifacts_root: Path,
    package: str,
    to_version: str,
    *,
    run_id: str | None = None,
    timeout_s: float = 900.0,
    verify_old_pin: bool = False,
    pytest_timeout_s: float = 300.0,
) -> PreparedTarget:
    del timeout_s, verify_old_pin, pytest_timeout_s
    assert run_id is not None
    run_dir = Path(artifacts_root) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    ledger = RunLedger(run_dir)
    ledger.append("setup", run_id=run_id, package=package, to_version=to_version)
    (run_dir / "setup.json").write_text(
        json.dumps({"status": "ok", "package": package, "to_version": to_version}),
        encoding="utf-8",
    )
    return PreparedTarget(
        run_id=run_id,
        run_dir=run_dir,
        repo=RepoWorkdir(root=run_dir, source=str(source), commit="deadbeef"),
        venv=VenvInfo(directory=run_dir / "venv", python="python"),
        ledger=ledger,
        setup_path=run_dir / "setup.json",
        versions={"python": "3.13.15", "pytest": "8.4.1", package: to_version},
    )


def _install_fakes(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace settings/prepare/run_upgrade in the runs module."""
    state: dict[str, Any] = {"release": threading.Event()}
    assert isinstance(state["release"], threading.Event)
    state["release"].set()

    def fake_upgrade(**kwargs: Any) -> UpgradeReport:
        ledger: RunLedger = kwargs["ledger"]
        run_id: str = kwargs["run_id"]
        report = UpgradeReport(
            run_id=run_id,
            request=kwargs["request"],
            status=VerifyStatus.GREEN,
            iterations_used=1,
        )
        ledger.append("baseline_verify", status="ok", detail="baseline GREEN")
        state["release"].wait(timeout=10.0)
        ledger.append("certify", status="ok", detail="certified GREEN")
        run_dir = Path(kwargs["artifacts_dir"]) / run_id
        (run_dir / "upgrade_report.json").write_text(
            report.model_dump_json(indent=2), encoding="utf-8"
        )
        (run_dir / "proof_card.md").write_text(proof_card_markdown(report), encoding="utf-8")
        return report

    monkeypatch.setattr("upgradepilot.web.runs.load_settings_for_run", _fake_settings)
    monkeypatch.setattr("upgradepilot.web.runs.prepare_target", _fake_prepare)
    monkeypatch.setattr("upgradepilot.web.runs.run_upgrade", fake_upgrade)
    return state


def _post_payload(repo: Path) -> dict[str, Any]:
    return {
        "repo": str(repo),
        "package": "pydantic",
        "to_version": "2.9.0",
        "max_iterations": 3,
    }


def test_start_run_streams_live_events_and_finishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fakes(monkeypatch)
    repo = tmp_path / "demo-repo"
    repo.mkdir()
    app = _make_app(tmp_path)
    client = TestClient(app)

    resp = client.post("/api/runs", json=_post_payload(repo))
    assert resp.status_code == 202
    run_id = resp.json()["run_id"]

    lines = _read_sse(client, run_id)
    joined = "\n".join(lines)
    assert '"event":"setup"' in joined
    assert '"event":"certify"' in joined
    assert any(line.startswith("event: done") for line in lines)

    controller = app.state.run_controller
    _wait_idle(controller)

    detail = client.get(f"/api/runs/{run_id}").json()
    assert detail["report"]["status"] == "GREEN"
    assert detail["proof_card"]
    assert detail["error"] is None

    runs = client.get("/api/runs").json()
    assert [r["run_id"] for r in runs] == [run_id]
    assert runs[0]["status"] == "GREEN"


def test_second_run_is_rejected_while_busy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _install_fakes(monkeypatch)
    state["release"].clear()  # hold the first run open
    repo = tmp_path / "demo-repo"
    repo.mkdir()
    app = _make_app(tmp_path)
    client = TestClient(app)

    first = client.post("/api/runs", json=_post_payload(repo))
    assert first.status_code == 202

    second = client.post("/api/runs", json=_post_payload(repo))
    assert second.status_code == 409
    assert "already in progress" in second.json()["detail"]

    state["release"].set()
    _wait_idle(app.state.run_controller)

    third = client.post("/api/runs", json=_post_payload(repo))
    assert third.status_code == 202
    state["release"].set()
    _wait_idle(app.state.run_controller)


def test_start_run_missing_keys_is_422(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_config() -> Settings:
        raise ConfigError("missing NEBIUS_API_KEY")

    monkeypatch.setattr("upgradepilot.web.runs.load_settings_for_run", raise_config)
    repo = tmp_path / "demo-repo"
    repo.mkdir()
    client = TestClient(_make_app(tmp_path))

    resp = client.post("/api/runs", json=_post_payload(repo))
    assert resp.status_code == 422
    assert "missing NEBIUS_API_KEY" in resp.json()["detail"]


def test_start_run_bad_repo_is_422(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("upgradepilot.web.runs.load_settings_for_run", _fake_settings)
    client = TestClient(_make_app(tmp_path))

    resp = client.post("/api/runs", json=_post_payload(tmp_path / "no-such-repo"))
    assert resp.status_code == 422
    assert "not a directory" in resp.json()["detail"]


def test_start_run_field_validation(tmp_path: Path) -> None:
    client = TestClient(_make_app(tmp_path))
    resp = client.post("/api/runs", json={"repo": str(tmp_path), "package": ""})
    assert resp.status_code == 422
    resp = client.post(
        "/api/runs",
        json={"repo": str(tmp_path), "package": "x", "to_version": "1", "max_iterations": 0},
    )
    assert resp.status_code == 422


# -- bench ------------------------------------------------------------------


def test_bench_endpoint_unavailable_without_module(tmp_path: Path) -> None:
    client = TestClient(_make_app(tmp_path))
    resp = client.get("/api/bench")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert body["rows"] == []


def test_bench_endpoint_returns_rows(tmp_path: Path) -> None:
    bench_dir = tmp_path / "bench"
    bench_dir.mkdir()
    (bench_dir / "results_table.py").write_text(
        "def build_results_table_json(art_root):\n"
        "    return [{'case_id': 'demo-case', 'pre_status': 'GREEN',"
        " 'post_status': 'ENV_FAIL', 'pre_passed': 12,"
        " 'post_failed': 3, 'post_errors': 1, 'post_duration_s': 1.5}]\n"
        "def build_results_table(art_root):\n"
        "    return '# Benchmark Results'\n",
        encoding="utf-8",
    )
    client = TestClient(_make_app(tmp_path))
    resp = client.get("/api/bench")
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is True
    assert body["rows"][0]["case_id"] == "demo-case"
    assert "Benchmark Results" in body["markdown"]
