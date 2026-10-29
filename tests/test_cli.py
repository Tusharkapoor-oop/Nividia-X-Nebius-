"""CLI contract tests for command options and agent loop invocation."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from upgradepilot.cli import app

runner = CliRunner()


def test_upgrade_requires_named_package_and_to_options(tmp_path: Path) -> None:
    positional = runner.invoke(app, ["upgrade", str(tmp_path), "pydantic", "2.9.0"])
    assert positional.exit_code == 2

    missing_to = runner.invoke(app, ["upgrade", str(tmp_path), "--package", "pydantic"])
    assert missing_to.exit_code == 2


def test_upgrade_command_invokes_agent_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from upgradepilot.config import Settings
    from upgradepilot.harness import RepoWorkdir, VenvInfo
    from upgradepilot.pipeline import UpgradeReport, UpgradeRequest
    from upgradepilot.prepare import PreparedTarget
    from upgradepilot.run_ledger import RunLedger
    from upgradepilot.verify import VerifyStatus

    mock_report = UpgradeReport(
        run_id="run-cli-test-001",
        request=UpgradeRequest(repo=str(tmp_path), package="pydantic", to_version="2.9.0"),
        status=VerifyStatus.GREEN,
    )
    prepared = PreparedTarget(
        run_id="run-cli-test-001",
        run_dir=tmp_path / "run",
        repo=RepoWorkdir(root=tmp_path / "repo", source=str(tmp_path), commit="HEAD"),
        venv=VenvInfo(directory=tmp_path / "venv", python="python"),
        ledger=RunLedger(tmp_path / "run"),
        setup_path=tmp_path / "run" / "setup.json",
    )
    settings = Settings(nebius_api_key="mock", tavily_api_key="mock")

    monkeypatch.setattr("upgradepilot.cli.load_settings_for_run", lambda: settings)
    monkeypatch.setattr("upgradepilot.prepare.prepare_target", lambda *a, **k: prepared)
    monkeypatch.setattr("upgradepilot.agent.run_upgrade", lambda **kwargs: mock_report)

    result = runner.invoke(
        app,
        ["upgrade", str(tmp_path), "--package", "pydantic", "--to", "2.9.0", "--json"],
    )
    assert result.exit_code == 0
    assert "run-cli-test-001" in result.output
    assert "GREEN" in result.output


def test_upgrade_command_reports_setup_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from upgradepilot.config import Settings
    from upgradepilot.prepare import PreparationError

    settings = Settings(nebius_api_key="mock", tavily_api_key="mock")
    monkeypatch.setattr("upgradepilot.cli.load_settings_for_run", lambda: settings)

    def fail_setup(*args: object, **kwargs: object) -> None:
        raise PreparationError("pip install failed for demo")

    monkeypatch.setattr("upgradepilot.prepare.prepare_target", fail_setup)

    result = runner.invoke(
        app,
        ["upgrade", str(tmp_path), "--package", "pydantic", "--to", "2.9.0", "--json"],
    )
    assert result.exit_code == 1
    assert "ENV_FAIL" in result.output
    assert "pip install failed" in result.output


def test_bench_list_prints_cases(monkeypatch: pytest.MonkeyPatch) -> None:
    """bench --list shows the benchmark case table and exits 0."""
    # Rich truncates long cell contents at the default 80-column console
    # width, so widen the console so full case ids fit in the table.
    monkeypatch.setenv("COLUMNS", "200")
    result = runner.invoke(app, ["bench", "--list"])
    assert result.exit_code == 0
    # Strip whitespace so wrapped cell content is matched too.
    flattened = result.output.replace("\n", "").replace(" ", "")
    assert "pytest-lazy-fixture-pytest7-to-8" in flattened


def test_bench_unknown_case_exits_2() -> None:
    result = runner.invoke(app, ["bench", "--case", "no-such-case"])
    assert result.exit_code == 2
