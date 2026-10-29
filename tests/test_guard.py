"""Offline tests for the test-suite guard (Phase 3 groundwork).

These pin the core anti-cheat rules:

- any modification, deletion, or addition inside the test surface is
  evidence the agent touched tests (CHEATED inputs);
- source-code edits are never flagged (that is where legitimate patches go);
- ``guarded_status`` folds guard evidence over pytest's own verdict.
"""

from __future__ import annotations

from pathlib import Path

from upgradepilot.guard import (
    GuardReport,
    GuardViolation,
    TestSuiteSnapshot,
    compare_snapshots,
    guarded_status,
    snapshot_tests,
)
from upgradepilot.verify import VerifyStatus

# pytest must not collect pydantic model classes imported into this module
# (their names match pytest's default python_classes pattern).
TestSuiteSnapshot.__test__ = False  # type: ignore[attr-defined]


def _write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _repo(tmp_path: Path) -> Path:
    """A tiny repo with source, tests, conftest, and pytest config."""
    root = tmp_path / "repo"
    _write(root, "src/pkg/app.py", "def add(a: int, b: int) -> int:\n    return a + b\n")
    _write(root, "tests/conftest.py", "import pytest\n")
    _write(root, "tests/test_app.py", "def test_add():\n    assert 1 + 1 == 2\n")
    _write(root, "pytest.ini", "[pytest]\naddopts = -q\n")
    return root


def test_snapshot_covers_names_conftest_and_config(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    snap = snapshot_tests(root)
    paths = [f.path for f in snap.files]
    assert paths == [
        "pytest.ini",
        "tests/conftest.py",
        "tests/test_app.py",
    ]


def test_snapshot_ignores_venv_git_cache(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    _write(root, ".venv/lib/site-packages/test_evil.py", "def test_v():\n    assert 0\n")
    _write(root, ".upv-venv/Lib/site-packages/test_evil.py", "def test_v():\n    assert 0\n")
    _write(root, ".git/hooks/test_hook.py", "#\n")
    _write(root, "src/pkg/__pycache__/test_cached.py", "#\n")
    snap = snapshot_tests(root)
    paths = [f.path for f in snap.files]
    assert all(not path.startswith((".venv", ".upv-venv")) for path in paths)
    assert "tests/test_app.py" in paths


def test_pyproject_is_part_of_guarded_surface(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    _write(root, "pyproject.toml", "[tool.pytest.ini_options]\naddopts = '-q'\n")
    snapshot = snapshot_tests(root)
    assert "pyproject.toml" in [f.path for f in snapshot.files]

    _write(root, "pyproject.toml", "[tool.pytest.ini_options]\naddopts = '-q -k safe'\n")
    report = compare_snapshots(snapshot, root)
    assert report.clean is False
    assert [(v.kind, v.path) for v in report.violations] == [("modified", "pyproject.toml")]


def test_weakened_assertion_is_flagged_as_modified(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    snapshot = snapshot_tests(root)
    _write(root, "tests/test_app.py", "def test_add():\n    assert True\n")
    report = compare_snapshots(snapshot, root)
    assert report.clean is False
    assert [(v.kind, v.path) for v in report.violations] == [("modified", "tests/test_app.py")]


def test_deleted_test_file_is_flagged(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    snapshot = snapshot_tests(root)
    (root / "tests/test_app.py").unlink()
    report = compare_snapshots(snapshot, root)
    assert report.clean is False
    assert [(v.kind, v.path) for v in report.violations] == [("deleted", "tests/test_app.py")]


def test_added_test_file_is_flagged(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    snapshot = snapshot_tests(root)
    _write(root, "tests/test_padding.py", "def test_nothing():\n    assert True\n")
    report = compare_snapshots(snapshot, root)
    assert report.clean is False
    assert [(v.kind, v.path) for v in report.violations] == [("added", "tests/test_padding.py")]


def test_conftest_and_pytestini_edits_are_flagged(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    snapshot = snapshot_tests(root)
    _write(root, "tests/conftest.py", "# changed\n")
    _write(root, "pytest.ini", "[pytest]\naddopts = -q -k evil\n")
    _write(root, "src/pkg/app.py", "def add(a: int, b: int) -> int:\n    return a * b\n")
    report = compare_snapshots(snapshot, root)
    flagged = sorted((v.kind, v.path) for v in report.violations)
    assert flagged == [
        ("modified", "pytest.ini"),
        ("modified", "tests/conftest.py"),
    ]


def test_source_patch_alone_is_not_flagged(tmp_path: Path) -> None:
    """Legitimate agent patching happens in source; the guard must allow it."""
    root = _repo(tmp_path)
    snapshot = snapshot_tests(root)
    _write(root, "src/pkg/app.py", "def add(a: int, b: int) -> int:\n    return a * b\n")
    report = compare_snapshots(snapshot, root)
    assert report.clean is True
    assert report.violations == []
    assert report.files_compared == 3


def test_snapshot_json_roundtrip(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    snapshot = snapshot_tests(root)
    path = tmp_path / "snapshot.json"
    snapshot.to_json(path)
    loaded = TestSuiteSnapshot.from_json(path)
    assert loaded == snapshot
    # A fresh snapshot made after the roundtrip matches the loaded baseline.
    assert compare_snapshots(loaded, root).clean is True


def test_guarded_status_folds_guard_evidence_over_pytest() -> None:
    dirty = GuardReport(clean=False, files_compared=2, violations=[])
    clean = GuardReport(clean=True, files_compared=2)

    assert guarded_status(VerifyStatus.GREEN, dirty) is VerifyStatus.CHEATED
    assert guarded_status(VerifyStatus.STUCK, dirty) is VerifyStatus.CHEATED
    assert guarded_status(VerifyStatus.ENV_FAIL, dirty) is VerifyStatus.CHEATED
    assert guarded_status(VerifyStatus.GREEN, clean) is VerifyStatus.GREEN
    assert guarded_status(VerifyStatus.STUCK, clean) is VerifyStatus.STUCK


def test_report_summary_text() -> None:
    dirty = GuardReport(
        clean=False,
        files_compared=1,
        violations=[GuardViolation(path="tests/test_app.py", kind="modified")],
    )
    clean = GuardReport(clean=True, files_compared=2)
    assert dirty.summary == "modified: tests/test_app.py"
    assert clean.summary == "clean (2 test files unchanged)"


def test_guard_flags_new_conftest_added(tmp_path: Path) -> None:
    """Agent creating a new conftest.py must be detected and flagged."""
    root = tmp_path / "repo"
    _write(root, "src/pkg/main.py", "x = 1\n")
    _write(root, "tests/test_one.py", "def test_one(): pass\n")
    snapshot = snapshot_tests(root)

    # Maliciously add a root conftest and a sub-conftest
    _write(root, "conftest.py", "def pytest_runtest_setup(): pass\n")
    _write(root, "tests/sub/conftest.py", "def pytest_collection_modifyitems(): pass\n")

    report = compare_snapshots(snapshot, root)
    assert report.clean is False
    violations = {v.path: v.kind for v in report.violations}
    assert violations.get("conftest.py") == "added"
    assert violations.get("tests/sub/conftest.py") == "added"
    assert guarded_status(VerifyStatus.GREEN, report) is VerifyStatus.CHEATED


def test_guard_flags_new_pytest_config_added(tmp_path: Path) -> None:
    """Agent dropping a new pytest.ini or tox.ini must be flagged."""
    root = tmp_path / "repo"
    _write(root, "src/pkg/main.py", "x = 1\n")
    _write(root, "tests/test_one.py", "def test_one(): pass\n")
    snapshot = snapshot_tests(root)

    _write(root, "pytest.ini", "[pytest]\naddopts = --ignore=tests/test_one.py\n")
    report = compare_snapshots(snapshot, root)
    assert report.clean is False
    assert any(v.path == "pytest.ini" and v.kind == "added" for v in report.violations)
    assert guarded_status(VerifyStatus.GREEN, report) is VerifyStatus.CHEATED


def test_guard_flags_shadowing_file(tmp_path: Path) -> None:
    """Agent dropping pydantic.py to fake the library must be flagged as shadowing."""
    root = tmp_path / "repo"
    _write(root, "src/pkg/main.py", "import pydantic\n")
    _write(root, "tests/test_one.py", "def test_one(): pass\n")
    snapshot = snapshot_tests(root)

    # Maliciously drop pydantic.py in repo root
    _write(root, "pydantic.py", "class BaseModel: pass\n")

    report = compare_snapshots(snapshot, root, package_name="pydantic")
    assert report.clean is False
    assert any(v.path == "pydantic.py" and v.kind == "shadowing" for v in report.violations)
    assert guarded_status(VerifyStatus.GREEN, report) is VerifyStatus.CHEATED


def test_guard_flags_shadowing_package_directory(tmp_path: Path) -> None:
    """Agent dropping a pydantic/ package directory must be flagged as shadowing."""
    root = tmp_path / "repo"
    _write(root, "src/pkg/main.py", "import pydantic\n")
    _write(root, "tests/test_one.py", "def test_one(): pass\n")
    snapshot = snapshot_tests(root)

    # Maliciously create a pydantic directory
    _write(root, "pydantic/__init__.py", "class BaseModel: pass\n")

    report = compare_snapshots(snapshot, root, package_name="pydantic")
    assert report.clean is False
    assert any(
        v.path == "pydantic/__init__.py" and v.kind == "shadowing" for v in report.violations
    )
    assert guarded_status(VerifyStatus.GREEN, report) is VerifyStatus.CHEATED


def test_guard_flags_newly_skipped_tests(tmp_path: Path) -> None:
    """Newly skipped tests compared to baseline must be flagged as CHEATED."""
    from upgradepilot.models import PytestResult

    root = tmp_path / "repo"
    _write(root, "tests/test_one.py", "def test_one(): pass\n")
    snapshot = snapshot_tests(root)

    base_res = PytestResult(exit_code=1, passed=5, failed=2, skipped=0)
    current_res = PytestResult(exit_code=0, passed=5, failed=0, skipped=2)

    report = compare_snapshots(
        snapshot, root, baseline_result=base_res, current_result=current_res
    )
    assert report.clean is False
    assert any(v.kind == "skipped_test" and "newly skipped" in v.detail for v in report.violations)
    assert guarded_status(VerifyStatus.GREEN, report) is VerifyStatus.CHEATED


def test_guard_flags_newly_xfailed_tests(tmp_path: Path) -> None:
    """Newly xfailed tests compared to baseline must be flagged as CHEATED."""
    from upgradepilot.models import PytestResult

    root = tmp_path / "repo"
    _write(root, "tests/test_one.py", "def test_one(): pass\n")
    snapshot = snapshot_tests(root)

    base_res = PytestResult(exit_code=1, passed=5, failed=2, xfailed=0)
    current_res = PytestResult(exit_code=0, passed=5, failed=0, xfailed=2)

    report = compare_snapshots(
        snapshot, root, baseline_result=base_res, current_result=current_res
    )
    assert report.clean is False
    assert any(v.kind == "skipped_test" and "newly xfailed" in v.detail for v in report.violations)
    assert guarded_status(VerifyStatus.GREEN, report) is VerifyStatus.CHEATED


def test_guard_compares_skips_against_the_old_pin_green_run(tmp_path: Path) -> None:
    """D1: a repaired suite is measured against the pre-bump GREEN run.

    The post-bump baseline here never collected (ENV_FAIL), so its skip
    profile is meaningless. The old-pin run had one legitimate skip and one
    xfail, and the repaired run has exactly the same profile: not cheating.
    """
    from upgradepilot.models import PytestResult

    root = tmp_path / "repo"
    _write(root, "tests/test_one.py", "def test_one(): pass\n")
    snapshot = snapshot_tests(root)

    old_pin_green = PytestResult(exit_code=0, passed=8, skipped=1, xfailed=1)
    post_bump_broken = PytestResult(exit_code=2, passed=0, skipped=0, xfailed=0)
    patched_green = PytestResult(exit_code=0, passed=8, skipped=1, xfailed=1)

    report = compare_snapshots(
        snapshot,
        root,
        baseline_result=post_bump_broken,
        current_result=patched_green,
        masking_reference=old_pin_green,
        masking_reference_label="old-pin GREEN run run-abc",
    )

    assert report.clean is True
    assert report.violations == []


def test_guard_still_flags_a_new_skip_against_the_old_pin_run(tmp_path: Path) -> None:
    """D1 keeps the anti-masking rule at full strength."""
    from upgradepilot.models import PytestResult

    root = tmp_path / "repo"
    _write(root, "tests/test_one.py", "def test_one(): pass\n")
    snapshot = snapshot_tests(root)

    old_pin_green = PytestResult(exit_code=0, passed=8, skipped=0, xfailed=0)
    post_bump_broken = PytestResult(exit_code=2, passed=0, skipped=0, xfailed=0)
    weakened = PytestResult(exit_code=0, passed=7, skipped=1)

    report = compare_snapshots(
        snapshot,
        root,
        baseline_result=post_bump_broken,
        current_result=weakened,
        masking_reference=old_pin_green,
        masking_reference_label="old-pin GREEN run run-abc",
    )

    assert report.clean is False
    detail = " ".join(violation.detail for violation in report.violations)
    assert "newly skipped" in detail
    assert "old-pin GREEN run run-abc: 0" in detail
    assert guarded_status(VerifyStatus.GREEN, report) is VerifyStatus.CHEATED
