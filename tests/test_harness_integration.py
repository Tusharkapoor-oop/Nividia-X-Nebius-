"""Offline integration tests for clone->venv->pytest end-to-end.

Uses a synthetic fixture repo created inside pytest's tmp_path; exercises
the real git/venv/subprocess paths (no network beyond pip's pytest wheel
for the fixture venv).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from upgradepilot.harness import (
    HarnessError,
    clone_pinned,
    make_pinned_venv,
    run_pytest,
)

pytestmark = [pytest.mark.subprocess]  # spawns real processes (git/venv/pip/pytest)


def _make_source_repo(src_root: Path) -> str:
    pkg = src_root / "demo_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mathy.py").write_text(
        "def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8"
    )
    tests = src_root / "tests"
    tests.mkdir()
    (tests / "test_mathy.py").write_text(
        "from demo_pkg.mathy import add\n\n\ndef test_add() -> None:\n    assert add(1, 2) == 3\n",
        encoding="utf-8",
    )
    (src_root / "pyproject.toml").write_text(
        "[project]\nname='demo-packages'\nversion='0.0.1'\n",
        encoding="utf-8",
    )
    for argv in (
        ["git", "init"],
        ["git", "add", "-A"],
        [
            "git",
            "-c",
            "user.name=fixture",
            "-c",
            "user.email=fixture@local",
            "commit",
            "-m",
            "init",
        ],
    ):
        subprocess.run(argv, cwd=src_root, check=True, capture_output=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=src_root, check=True, capture_output=True, text=True
    ).stdout.strip()
    return head


def _venv_pytest_available(venv_python: str) -> bool:
    probe = subprocess.run(
        [venv_python, "-m", "pytest", "--version"], capture_output=True, text=True
    )
    return probe.returncode == 0


def test_clone_venv_pytest_end_to_end(tmp_path: Path) -> None:
    src = tmp_path / "source_repo"
    src.mkdir()
    head = _make_source_repo(src)
    _ = clone_pinned(str(src), head, tmp_path / "workdirs")
    target = tmp_path / "workdirs" / "source_repo"
    assert (target / "tests" / "test_mathy.py").exists()

    from upgradepilot.harness import pip_install

    venv = make_pinned_venv(target)
    if not _venv_pytest_available(venv.python):
        pip_install(venv, "pytest")

    result = run_pytest(venv, target, timeout_s=120.0)
    assert result.ok, "\n".join(result.output_tail)
    assert result.passed == 1

    assert result.failed == 0
    assert result.collected_anything


def test_run_pytest_timeout_kills_tree(tmp_path: Path) -> None:
    src = tmp_path / "source_repo"
    src.mkdir()
    head = _make_source_repo(src)
    tests = src / "tests"
    (tests / "test_slow.py").write_text(
        "import time\n\n\ndef test_sleeps() -> None:\n    time.sleep(30)\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=src, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=fixture",
            "-c",
            "user.email=fixture@local",
            "commit",
            "-m",
            "slow",
        ],
        cwd=src,
        check=True,
        capture_output=True,
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=src, check=True, capture_output=True, text=True
    ).stdout.strip()
    _ = clone_pinned(str(src), head, tmp_path / "workdirs")
    target = tmp_path / "workdirs" / "source_repo"

    from upgradepilot.harness import pip_install

    venv = make_pinned_venv(target)
    if not _venv_pytest_available(venv.python):
        pip_install(venv, "pytest")

    with pytest.raises(HarnessError, match="timeout after"):
        run_pytest(venv, target, timeout_s=2.0)


def test_run_pytest_ignores_ancestor_config(tmp_path: Path) -> None:
    """A workdir nested below a foreign pyproject must not inherit it.

    Regression for the real incident: bench workdirs live inside this repo,
    and pytest walked up from the clone into *our* pyproject.toml
    (``minversion`` mismatch -> exit 4). The child run must pin its own
    config instead.
    """
    src = tmp_path / "source_repo"
    src.mkdir()
    head = _make_source_repo(src)
    _ = clone_pinned(str(src), head, tmp_path / "workdirs")
    target = tmp_path / "workdirs" / "source_repo"
    # Poisonous ancestor between tmp_path and the workdirs — mirrors our
    # repo pyproject sitting above bench/workdirs/cases/<repo>.
    (tmp_path / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\nminversion = '99.0'\n",
        encoding="utf-8",
    )

    from upgradepilot.harness import pip_install

    venv = make_pinned_venv(target)
    if not _venv_pytest_available(venv.python):
        pip_install(venv, "pytest")

    result = run_pytest(venv, target, timeout_s=120.0)
    assert result.ok, "\n".join(result.output_tail)
    assert result.passed == 1


def test_resolved_versions_reads_the_interpreter_and_installed_packages() -> None:
    """D4: version evidence is read from the venv, not assumed."""
    import sys

    from upgradepilot.harness import VenvInfo, resolved_versions

    venv = VenvInfo(directory=Path(sys.executable).parent.parent, python=sys.executable)
    versions = resolved_versions(venv, "pytest", "definitely-not-installed-pkg")

    assert versions["python"].startswith("3.")
    assert versions["pytest"] != "not-installed"
    assert versions["definitely-not-installed-pkg"] == "not-installed"
    assert "error" not in versions
