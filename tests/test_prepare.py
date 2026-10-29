"""Offline tests for the disposable-checkout setup boundary (Phase 4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from upgradepilot.harness import HarnessError, VenvInfo
from upgradepilot.models import PytestResult
from upgradepilot.prepare import PreparationError, install_bump, prepare_target
from upgradepilot.run_ledger import RunLedger
from upgradepilot.verify import VerifyOutcome, VerifyStatus


def _source(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    (source / "src" / "pkg").mkdir(parents=True)
    (source / "src" / "pkg" / "app.py").write_text("x = 1\n", encoding="utf-8")
    (source / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\nversion = '1.0'\n", encoding="utf-8"
    )
    (source / ".git").mkdir()
    (source / ".git" / "config").write_text("secret-ish metadata\n", encoding="utf-8")
    (source / ".venv").mkdir()
    (source / ".venv" / "marker.py").write_text("x = 0\n", encoding="utf-8")
    (source / ".upv-venv").mkdir()
    (source / ".upv-venv" / "marker.py").write_text("x = 0\n", encoding="utf-8")
    (source / "artifacts").mkdir()
    (source / "artifacts" / "old-run.json").write_text("{}", encoding="utf-8")
    return source


def _fake_versions(venv: VenvInfo, package: str) -> dict[str, str]:
    """Version record that reports whatever the last install asked for."""
    del venv
    return {"python": "3.13.15", "pytest": "8.4.1", package: "asked"}


def test_prepare_copies_repo_and_records_setup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path)
    calls: list[tuple[str, ...]] = []

    def fake_venv(repo_root: Path) -> VenvInfo:
        venv_dir = repo_root / ".upv-venv"
        return VenvInfo(directory=venv_dir, python="python")

    def fake_pip(venv: VenvInfo, *args: str, timeout_s: float = 0.0) -> str:
        calls.append(args)
        return "installed"

    monkeypatch.setattr("upgradepilot.prepare.make_pinned_venv", fake_venv)
    monkeypatch.setattr("upgradepilot.prepare.pip_install", fake_pip)
    monkeypatch.setattr("upgradepilot.prepare.resolved_versions", _fake_versions)

    prepared = prepare_target(
        source,
        tmp_path / "artifacts" / "runs",
        "demo",
        "2.0",
        run_id="run-setup-test",
    )

    assert prepared.run_id == "run-setup-test"
    assert prepared.repo.root == tmp_path / "artifacts" / "runs" / "run-setup-test" / "repo"
    assert (prepared.repo.root / "src" / "pkg" / "app.py").is_file()
    assert not (prepared.repo.root / ".git").exists()
    assert not (prepared.repo.root / ".venv").exists()
    assert not (prepared.repo.root / ".upv-venv").exists()
    assert not (prepared.repo.root / "artifacts").exists()
    assert calls == [("-e", "."), ("pytest",), ("pytest-mock",), ("demo==2.0",)]

    setup = json.loads(prepared.setup_path.read_text(encoding="utf-8"))
    assert setup["status"] == "ok"
    assert setup["package"] == "demo"
    assert setup["to_version"] == "2.0"
    assert setup["versions"]["after_bump"]["pytest"] == "8.4.1"
    assert prepared.versions["pytest"] == "8.4.1"
    events = [event.event for event in prepared.ledger.read_all()]
    assert events[0] == "setup"
    assert "install" in events
    assert events[-1] == "setup_ok"


def test_prepare_records_failure_and_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path)
    monkeypatch.setattr(
        "upgradepilot.prepare.make_pinned_venv",
        lambda repo_root: VenvInfo(directory=repo_root / ".upv-venv", python="python"),
    )

    def fail_pip(venv: VenvInfo, *args: str, timeout_s: float = 0.0) -> str:
        raise HarnessError("dependency resolver failed")

    monkeypatch.setattr("upgradepilot.prepare.pip_install", fail_pip)

    with pytest.raises(PreparationError, match="dependency resolver failed"):
        prepare_target(
            source,
            tmp_path / "artifacts" / "runs",
            "demo",
            "2.0",
            run_id="run-setup-fail",
        )

    run_dir = tmp_path / "artifacts" / "runs" / "run-setup-fail"
    setup = json.loads((run_dir / "setup.json").read_text(encoding="utf-8"))
    assert setup["status"] == "failed"
    events = [event.event for event in RunLedger(run_dir).read_all()]
    assert "setup_failed" in events


def test_prepare_installs_the_old_pin_before_the_bump(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D4: the bump lands on the old pin, and both stages are recorded."""
    source = _source(tmp_path)
    calls: list[tuple[str, ...]] = []

    def fake_venv(repo_root: Path) -> VenvInfo:
        return VenvInfo(directory=repo_root / ".upv-venv", python="python")

    def fake_pip(venv: VenvInfo, *args: str, timeout_s: float = 0.0) -> str:
        calls.append(args)
        return "installed"

    def fake_resolved(venv: VenvInfo, package: str) -> dict[str, str]:
        del venv
        asked = next(
            (args[0].split("==", 1)[1] for args in reversed(calls) if args and "==" in args[0]),
            "1.0",
        )
        return {"python": "3.13.15", "pytest": "8.4.1", package: asked}

    monkeypatch.setattr("upgradepilot.prepare.make_pinned_venv", fake_venv)
    monkeypatch.setattr("upgradepilot.prepare.pip_install", fake_pip)
    monkeypatch.setattr("upgradepilot.prepare.resolved_versions", fake_resolved)

    prepared = prepare_target(
        source,
        tmp_path / "artifacts" / "runs",
        "demo",
        "2.0",
        from_version="1.0",
        run_id="run-old-pin-order",
    )

    assert calls == [
        ("-e", "."),
        ("pytest",),
        ("pytest-mock",),
        ("demo==1.0",),
        ("demo==2.0",),
    ]
    assert prepared.version_stages["after_old_pin"]["demo"] == "1.0"
    assert prepared.version_stages["after_bump"]["demo"] == "2.0"
    assert prepared.versions["demo"] == "2.0"

    setup = json.loads(prepared.setup_path.read_text(encoding="utf-8"))
    assert setup["from_version"] == "1.0"
    assert setup["versions"]["after_old_pin"]["demo"] == "1.0"
    assert setup["versions"]["after_bump"]["demo"] == "2.0"


def test_prepare_records_the_old_pin_reference_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D1/D4: the old-pin suite is run while the old pin is still installed."""
    source = _source(tmp_path)
    calls: list[tuple[str, ...]] = []
    verify_calls: list[str] = []

    def fake_venv(repo_root: Path) -> VenvInfo:
        return VenvInfo(directory=repo_root / ".upv-venv", python="python")

    def fake_pip(venv: VenvInfo, *args: str, timeout_s: float = 0.0) -> str:
        calls.append(args)
        return "installed"

    def fake_resolved(venv: VenvInfo, package: str) -> dict[str, str]:
        del venv
        asked = next(
            (args[0].split("==", 1)[1] for args in reversed(calls) if args and "==" in args[0]),
            "1.0",
        )
        return {"python": "3.13.15", "pytest": "8.4.1", package: asked}

    def fake_verify(*args: object, **kwargs: object) -> VerifyOutcome:
        # The old pin must still be installed when the reference suite runs.
        verify_calls.append(calls[-1][0])
        return VerifyOutcome(
            status=VerifyStatus.GREEN,
            run_id="setup-old-pin",
            result=PytestResult(exit_code=0, passed=20, skipped=1),
        )

    monkeypatch.setattr("upgradepilot.prepare.make_pinned_venv", fake_venv)
    monkeypatch.setattr("upgradepilot.prepare.pip_install", fake_pip)
    monkeypatch.setattr("upgradepilot.prepare.resolved_versions", fake_resolved)
    monkeypatch.setattr("upgradepilot.prepare.verify", fake_verify)

    prepared = prepare_target(
        source,
        tmp_path / "artifacts" / "runs",
        "demo",
        "2.0",
        verify_old_pin=True,
        run_id="run-reference",
    )

    # The project itself pinned demo 1.0, so that is the reference pin.
    assert verify_calls == ["demo==1.0"]
    assert calls[-1] == ("demo==2.0",)
    assert prepared.reference_outcome is not None
    assert prepared.reference_outcome.status is VerifyStatus.GREEN

    setup = json.loads(prepared.setup_path.read_text(encoding="utf-8"))
    assert setup["from_version"] == "1.0"
    assert setup["old_pin_reference"]["status"] == "GREEN"
    assert setup["old_pin_reference"]["skipped"] == 1
    reference_file = Path(setup["old_pin_reference"]["path"])
    assert reference_file.is_file()


def test_install_bump_records_new_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(tmp_path)
    calls: list[tuple[str, ...]] = []

    def fake_venv(repo_root: Path) -> VenvInfo:
        return VenvInfo(directory=repo_root / ".upv-venv", python="python")

    def fake_pip(venv: VenvInfo, *args: str, timeout_s: float = 0.0) -> str:
        calls.append(args)
        return "installed"

    def fake_resolved(venv: VenvInfo, package: str) -> dict[str, str]:
        del venv
        asked = next(
            (args[0].split("==", 1)[1] for args in reversed(calls) if args and "==" in args[0]),
            "1.0",
        )
        return {"python": "3.13.15", "pytest": "8.4.1", package: asked}

    monkeypatch.setattr("upgradepilot.prepare.make_pinned_venv", fake_venv)
    monkeypatch.setattr("upgradepilot.prepare.pip_install", fake_pip)
    monkeypatch.setattr("upgradepilot.prepare.resolved_versions", fake_resolved)

    prepared = prepare_target(
        source, tmp_path / "artifacts" / "runs", "demo", "1.0", run_id="run-two-phase"
    )
    assert prepared.versions["demo"] == "1.0"

    bumped = install_bump(prepared, "demo", "2.0")
    assert calls[-1] == ("demo==2.0",)
    assert bumped.versions["demo"] == "2.0"
    setup = json.loads(bumped.setup_path.read_text(encoding="utf-8"))
    assert setup["versions"]["after_bump"]["demo"] == "2.0"


def test_prepare_rejects_existing_run_directory(tmp_path: Path) -> None:
    source = _source(tmp_path)
    (tmp_path / "artifacts" / "runs" / "taken").mkdir(parents=True)
    with pytest.raises(PreparationError, match="already exists"):
        prepare_target(source, tmp_path / "artifacts" / "runs", "demo", "2.0", run_id="taken")


def test_prepare_rejects_unsafe_run_id(tmp_path: Path) -> None:
    source = _source(tmp_path)
    with pytest.raises(PreparationError, match="unsafe run id"):
        prepare_target(source, tmp_path / "artifacts" / "runs", "demo", "2.0", run_id="../escape")
