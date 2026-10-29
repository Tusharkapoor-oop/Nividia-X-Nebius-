"""Unit tests for event status mapping and the run ledger."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from upgradepilot.models import PytestResult
from upgradepilot.run_ledger import RunLedger
from upgradepilot.verify import VerifyStatus, classify_pytest


def _result(code: int, tail: list[str]) -> PytestResult:
    return PytestResult(exit_code=code, output_tail=tail)


def test_green_when_exit_zero() -> None:
    r = _result(0, ["... all passed", "5 passed in 1s"])
    assert classify_pytest(r) is VerifyStatus.GREEN


def test_stuck_on_plain_failures() -> None:
    r = _result(1, ["...", "2 failed, 1 passed in 0.5s"])
    assert classify_pytest(r) is VerifyStatus.STUCK


def test_env_fail_on_collector_and_usage_and_no_tests() -> None:
    assert classify_pytest(_result(2, ["errors collected"])) is VerifyStatus.ENV_FAIL
    assert classify_pytest(_result(4, ["usage:"])) is VerifyStatus.ENV_FAIL
    assert classify_pytest(_result(5, [])) is VerifyStatus.ENV_FAIL
    assert classify_pytest(_result(3, [])) is VerifyStatus.ENV_FAIL


def test_env_fail_on_missing_dependency() -> None:
    tail = ["ModuleNotFoundError: No module named 'legacy_lib'"]
    assert classify_pytest(_result(1, tail)) is VerifyStatus.ENV_FAIL


def test_run_ledger_roundtrip(tmp_path: Path) -> None:
    ledger = RunLedger(tmp_path / "run1")
    ledger.append("verify", status="GREEN", passed=5)
    ledger.append("verify", status="STUCK", failed=2)

    events = ledger.read_all()
    assert [e.event for e in events] == ["verify", "verify"]
    assert events[0].data["status"] == "GREEN"
    assert events[1].data["failed"] == 2
    assert ledger.path.name == "events.jsonl"


def test_verify_with_rollback_keeps_partial_progress(tmp_path: Path) -> None:
    """Verify outcome with strictly fewer failures keeps the modified tree."""
    from upgradepilot.harness import RepoWorkdir, VenvInfo
    from upgradepilot.verify import VerifyOutcome, verify_with_rollback

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    source_file = repo_root / "app.py"
    source_file.write_text("x = 1\n", encoding="utf-8")

    repo = RepoWorkdir(root=repo_root, source=str(repo_root), commit="HEAD")
    venv = VenvInfo(directory=tmp_path / "venv", python="python")

    # The patch step edits app.py while the verifier runs (as the agent loop
    # does), then reports 2 failures (previous was 5 -> strictly decreased!)
    def fake_verify(*args: Any, **kwargs: Any) -> VerifyOutcome:
        source_file.write_text("x = 2\n", encoding="utf-8")
        return VerifyOutcome(
            status=VerifyStatus.STUCK,
            run_id="run-partial",
            result=PytestResult(exit_code=1, passed=3, failed=2),
        )

    outcome = verify_with_rollback(
        repo, venv, timeout_s=30.0, previous_failures=5, verify_fn=fake_verify
    )

    # Patch is kept because 2 < 5
    assert outcome.status is VerifyStatus.STUCK
    assert any("partial_progress: kept patch" in r for r in outcome.reasons)
    assert source_file.read_text(encoding="utf-8") == "x = 2\n"


def test_verify_with_rollback_reverts_when_no_progress(tmp_path: Path) -> None:
    """Verify outcome with equal or more failures rolls back the modified tree."""
    from upgradepilot.harness import RepoWorkdir, VenvInfo
    from upgradepilot.verify import VerifyOutcome, verify_with_rollback

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    source_file = repo_root / "app.py"
    source_file.write_text("x = 1\n", encoding="utf-8")

    repo = RepoWorkdir(root=repo_root, source=str(repo_root), commit="HEAD")
    venv = VenvInfo(directory=tmp_path / "venv", python="python")

    # The patch step edits app.py while the verifier runs, then reports 5
    # failures (previous was 5 -> no decrease -> rollback required)
    def fake_verify(*args: Any, **kwargs: Any) -> VerifyOutcome:
        source_file.write_text("x = 999\n", encoding="utf-8")
        return VerifyOutcome(
            status=VerifyStatus.STUCK,
            run_id="run-stagnant",
            result=PytestResult(exit_code=1, passed=1, failed=5),
        )

    outcome = verify_with_rollback(
        repo, venv, timeout_s=30.0, previous_failures=5, verify_fn=fake_verify
    )

    # Patch must be rolled back because 5 is not < 5
    assert outcome.status is VerifyStatus.STUCK
    assert any("rollback: restored" in r for r in outcome.reasons)
    assert source_file.read_text(encoding="utf-8") == "x = 1\n"
