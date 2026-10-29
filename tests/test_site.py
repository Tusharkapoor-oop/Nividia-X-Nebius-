"""Tests for the static recorded-runs site: real data only, honest empty states."""

from __future__ import annotations

import json
from pathlib import Path

from upgradepilot.site import build_site, collect


def _agent_report(artifacts: Path, run_id: str, status: str = "GREEN") -> Path:
    run_dir = artifacts / "runs" / run_id
    run_dir.mkdir(parents=True)
    report = {
        "run_id": run_id,
        "request": {"repo": "demo-repo", "package": "pydantic", "to_version": "2.12.4"},
        "status": status,
        "iterations_used": 2,
        "steps": [
            {"step": "triage", "status": "ok", "detail": "query", "tier": "cheap"},
            {"step": "verify_1", "status": "ok", "detail": "GREEN", "tier": None},
        ],
        "cost": {
            "total_prompt_tokens": 120,
            "total_completion_tokens": 30,
            "total_cost_usd": 0.0,
            "calls": 2,
            "unpriced_calls": 2,
        },
        "provider": "nvidia-nim",
        "run_class": "dev",
        "models": {"default": "nvidia/test-model"},
        "versions": {"python": "3.13.15", "pytest": "8.4.1", "pydantic": "1.10.22"},
        "split": {"visible": ["tests/test_a.py"], "held_out": ["tests/test_b.py"]},
        "visible_outcome": {
            "status": "GREEN",
            "result": {"exit_code": 0, "passed": 20, "failed": 0, "errors": 0},
        },
        "guard_clean": True,
        "guard_summary": "clean",
    }
    (run_dir / "upgrade_report.json").write_text(json.dumps(report), encoding="utf-8")
    (run_dir / "proof_card.md").write_text("# Proof card\n\n- Verdict: GREEN\n", encoding="utf-8")
    return run_dir


def _strategy_result(artifacts: Path, case: str, strategy: str) -> Path:
    path = artifacts / "phase5" / case / strategy / "result.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "case_id": case,
                "strategy": strategy,
                "status": "STUCK",
                "exit_code": 1,
                "passed": 3,
                "failed": 2,
                "errors": 0,
                "llm_calls": 1,
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "cost_usd": None,
                "fully_priced": False,
                "provider": "nvidia-nim",
                "run_class": "dev",
                "recorded_at": "2026-10-27T10:00:00Z",
                "notes": ["post-bump suite before any repair: ENV_FAIL"],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_site_renders_recorded_runs_with_provider_labels(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    _agent_report(artifacts, "run-20261023T034032-c06f8b")
    _strategy_result(artifacts, "case-one", "agent")

    site = build_site(artifacts, tmp_path / "docs")

    assert len(site.records) == 2
    assert site.problems == []
    index = (tmp_path / "docs" / "index.html").read_text(encoding="utf-8")
    assert "Recorded runs, newest first" in index
    assert "NVIDIA NIM (dev run - not submission-eligible)" in index
    assert "not a live service" in index
    assert (tmp_path / "docs" / ".nojekyll").is_file()
    assert (tmp_path / "docs" / "styles.css").is_file()


def test_site_detail_page_shows_timeline_and_proof_card(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    run_dir = _agent_report(artifacts, "run-20261023T034032-c06f8b")
    record_dir = tmp_path / "docs" / "data"

    site = build_site(artifacts, tmp_path / "docs")
    record = next(r for r in site.records if r.kind == "agent")
    page = (tmp_path / "docs" / "runs" / f"{record.slug}.html").read_text(encoding="utf-8")

    assert "Timeline" in page
    assert "triage" in page
    assert "Proof card" in page
    assert "Verdict: GREEN" in page
    assert "2026-10-23T03:40:32Z" in page
    assert "Recorded run" in page
    assert (record_dir / record.slug / "artifact.json").is_file()
    assert (run_dir / "upgrade_report.json").is_file()


def test_site_empty_state_when_no_runs_exist(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    site = build_site(artifacts, tmp_path / "docs")

    assert site.records == []
    index = (tmp_path / "docs" / "index.html").read_text(encoding="utf-8")
    assert "No recorded runs found" in index
    assert "placeholder data" in index


def test_site_reports_unreadable_artifacts_instead_of_hiding_them(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    bad = artifacts / "runs" / "run-broken" / "upgrade_report.json"
    bad.parent.mkdir(parents=True)
    bad.write_text("{not json", encoding="utf-8")

    site = build_site(artifacts, tmp_path / "docs")
    index = (tmp_path / "docs" / "index.html").read_text(encoding="utf-8")

    assert site.problems
    assert "Unreadable artifacts" in index
    assert "run-broken" in index
    assert "JSONDecodeError" in index


def test_site_comparison_keeps_demo_and_benchmark_apart(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    demo = artifacts / "demo" / "demo-case" / "agent" / "result.json"
    demo.parent.mkdir(parents=True)
    demo.write_text(
        json.dumps(
            {
                "case_id": "demo-case",
                "strategy": "agent",
                "status": "GREEN",
                "suite": "30P/0F/0E (exit 0)",
                "provider": "nvidia-nim",
                "run_class": "dev",
                "recorded_at": "2026-10-28T04:00:00Z",
                "heldout_after": {"status": "GREEN", "passed": 11, "failed": 0},
            }
        ),
        encoding="utf-8",
    )

    build_site(artifacts, tmp_path / "docs")
    page = (tmp_path / "docs" / "comparison.html").read_text(encoding="utf-8")

    assert "Demo case (not a benchmark)" in page
    assert "No benchmark strategies recorded yet" in page
    assert "demo-case: agent" in page
    assert "held-out GREEN: 11 passed, 0 failed" in page


def test_site_escapes_artifact_text(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    run_dir = artifacts / "runs" / "run-20260101T000000-abcdef"
    run_dir.mkdir(parents=True)
    run_dir.joinpath("upgrade_report.json").write_text(
        json.dumps(
            {
                "run_id": "run-20260101T000000-abcdef",
                "request": {
                    "repo": "<script>alert(1)</script>",
                    "package": "pydantic",
                    "to_version": "2.0",
                },
                "status": "STUCK",
                "steps": [
                    {
                        "step": "triage",
                        "status": "ok",
                        "detail": "<img src=x onerror=alert(1)>",
                    }
                ],
                "provider": "nvidia-nim",
                "run_class": "dev",
            }
        ),
        encoding="utf-8",
    )

    site = build_site(artifacts, tmp_path / "docs")
    record = site.records[0]
    page = (tmp_path / "docs" / "runs" / f"{record.slug}.html").read_text(encoding="utf-8")

    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page
    assert "&lt;img src=x onerror=alert(1)&gt;" in page


def test_public_site_redacts_secrets_and_local_paths_without_mutating_source(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    run_dir = _agent_report(artifacts, "run-20261023T034032-c06f8b")
    report_path = run_dir / "upgrade_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["request"]["repo"] = r"C:\\Users\\ACER\\src\\private-repo"
    report["steps"][0]["detail"] = "auth=Bearer sk-abcdefghijklmnop12345"
    original = json.dumps(report)
    report_path.write_text(original, encoding="utf-8")
    (run_dir / "proof_card.md").write_text(
        r"Path: C:\\Users\\ACER\\src\\private-repo\nkey: tvly-abcdefghijklmnopqrstuvwxyz\n",
        encoding="utf-8",
    )

    site = build_site(artifacts, tmp_path / "docs")
    record = next(r for r in site.records if r.kind == "agent")
    page = (tmp_path / "docs" / "runs" / f"{record.slug}.html").read_text(encoding="utf-8")
    public_artifact = (tmp_path / "docs" / "data" / record.slug / "artifact.json").read_text(
        encoding="utf-8"
    )
    public_proof = (tmp_path / "docs" / "data" / record.slug / "proof_card.md").read_text(
        encoding="utf-8"
    )

    assert "ACER" not in page + public_artifact + public_proof
    assert "<redacted>" in public_artifact + public_proof
    assert "<local-user-path>" in public_artifact + public_proof
    assert report_path.read_text(encoding="utf-8") == original


def test_collect_survives_a_missing_artifacts_directory(tmp_path: Path) -> None:
    site = collect(tmp_path / "missing")
    assert site.records == []
    assert site.problems and "does not exist" in site.problems[0][1]
