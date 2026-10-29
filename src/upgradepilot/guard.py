"""Guard: prove the agent did not weaken, skip, or doctor the test suite.

The guard hashes the repo's test surface before the agent starts and
re-hashes it after patching. Test files are agent off-limits; this module is
the mechanism that turns that promise into checkable evidence:

- ``snapshot_tests``      hashes the test surface once, before patching.
- ``compare_snapshots``   returns ``GuardReport`` with per-file evidence.
- ``guarded_status``      folds the report into the outcome: any guard
                          violation upgrades the status to ``CHEATED``,
                          ahead of whatever pytest reported.

Scope is deliberately exact so legitimate patches are never flagged:

- guarded: pytest test files by name, every ``conftest.py``, and pytest
  config files (they can silently change collection or skipping).
- never:   application/library source. Patching source is the agent's job.

Status ``OVERFIT`` (held-out set) never comes from the guard: it is produced
by the held-out split (``upgradepilot.heldout``) when visible tests pass but
held-out tests fail. ``CHEATED`` is produced here only.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from upgradepilot.models import PytestResult
from upgradepilot.verify import VerifyStatus

# Directories that can never contain the target repo's own test surface.
SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        ".upv-venv",
        "env",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        ".tox",
        "dist",
        "build",
        ".build",
    }
)

# Files that count as the test surface wherever they appear in the tree.
TEST_FILE_NAMES = ("test_*.py", "*_test.py")

# Files that may silently alter collection, marking, or skipping.
# ``pyproject.toml`` is included because it can carry
# ``[tool.pytest.ini_options]``; the agent must never tune the suite through it.
GUARDED_CONFIG_NAMES = (
    "pytest.ini",
    ".pytest.ini",
    "tox.ini",
    "setup.cfg",
    "conftest.py",
    "pyproject.toml",
)


class GuardViolation(BaseModel):
    """One concrete difference or evasion detected on the test surface."""

    path: str
    kind: Literal["modified", "deleted", "added", "skipped_test", "shadowing"]
    detail: str = ""


class TestFileSnapshot(BaseModel):
    """Content fingerprint of one test-surface file."""

    path: str  # repo-relative, forward slashes
    sha256: str
    size: int


class TestSuiteSnapshot(BaseModel):
    """The complete hashed test surface of one repo at one point in time."""

    root: str
    created_at: str = ""
    files: list[TestFileSnapshot] = Field(default_factory=list)
    all_repo_files: list[str] = Field(default_factory=list)

    def to_json(self, path: Path) -> Path:
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        return path

    @classmethod
    def from_json(cls, path: Path) -> TestSuiteSnapshot:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))


class GuardReport(BaseModel):
    """Result of re-hashing the test surface against a snapshot."""

    clean: bool
    files_compared: int
    violations: list[GuardViolation] = Field(default_factory=list)

    @property
    def summary(self) -> str:
        if self.clean:
            return f"clean ({self.files_compared} test files unchanged)"
        parts: list[str] = []
        for v in self.violations:
            if v.detail:
                parts.append(f"{v.kind}: {v.path} ({v.detail})")
            else:
                parts.append(f"{v.kind}: {v.path}")
        return "; ".join(parts)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_test_file(path: Path) -> bool:
    return any(path.match(pattern) for pattern in TEST_FILE_NAMES)


def _is_guarded_file(path: Path) -> bool:
    return path.name in GUARDED_CONFIG_NAMES


def _is_skipped(part: str) -> bool:
    return part in SKIP_DIRS or part.endswith(".egg-info")


def _iter_files(repo_root: Path) -> list[Path]:
    """All files in the tree, skipping venv/git/cache/build directories."""
    files: list[Path] = []
    for path in sorted(repo_root.rglob("*")):
        if any(_is_skipped(part) for part in path.relative_to(repo_root).parts):
            continue
        if path.is_file():
            files.append(path)
    return files


def test_files(repo_root: Path) -> list[Path]:
    """The repo's test surface: named test files, conftest, pytest configs.

    Sorted by path so snapshots are stable regardless of filesystem order.
    """
    return sorted(
        (path for path in _iter_files(repo_root) if _is_test_file(path) or _is_guarded_file(path)),
        key=lambda p: p.relative_to(repo_root).as_posix(),
    )


def snapshot_tests(repo_root: Path) -> TestSuiteSnapshot:
    """Hash the test surface now; store this before any patching begins."""
    files = [
        TestFileSnapshot(
            path=path.relative_to(repo_root).as_posix(),
            sha256=_sha256(path),
            size=path.stat().st_size,
        )
        for path in test_files(repo_root)
    ]
    all_files = [path.relative_to(repo_root).as_posix() for path in _iter_files(repo_root)]
    return TestSuiteSnapshot(
        root=repo_root.name,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        files=files,
        all_repo_files=all_files,
    )


def check_skipped_or_xfailed(
    reference_result: PytestResult,
    current_result: PytestResult,
    *,
    reference_label: str = "baseline",
) -> list[GuardViolation]:
    """Flag newly skipped or xfailed tests as an evasion attempt.

    The reference must be a run that *actually collected* the suite: the
    skin of a suite is its skip/xfail profile, so it is measured against the
    last known-good (pre-bump GREEN) run. Comparing against a post-bump run
    that failed to collect would treat every skip in a repaired suite as a
    new one (see D1 in artifacts/phase5/REPORT.md).
    """
    violations: list[GuardViolation] = []
    if current_result.skipped > reference_result.skipped:
        diff = current_result.skipped - reference_result.skipped
        violations.append(
            GuardViolation(
                path="pytest.summary",
                kind="skipped_test",
                detail=(
                    f"{diff} newly skipped test(s) ({reference_label}: "
                    f"{reference_result.skipped}, current: {current_result.skipped})"
                ),
            )
        )
    if current_result.xfailed > reference_result.xfailed:
        diff = current_result.xfailed - reference_result.xfailed
        violations.append(
            GuardViolation(
                path="pytest.summary",
                kind="skipped_test",
                detail=(
                    f"{diff} newly xfailed test(s) ({reference_label}: "
                    f"{reference_result.xfailed}, current: {current_result.xfailed})"
                ),
            )
        )
    return violations


def check_shadowing_files(
    repo_root: Path,
    package_name: str,
    baseline_paths: set[str] | None = None,
) -> list[GuardViolation]:
    """Flag newly created files or modules that shadow the upgraded package.

    For example, when upgrading 'pydantic', creating 'pydantic.py' or a
    'pydantic/' directory in the repo intercepts imports with fake stubs.
    """
    violations: list[GuardViolation] = []
    if not package_name.strip():
        return violations

    norm_pkg = package_name.strip().lower()
    candidate_names = {
        norm_pkg,
        norm_pkg.replace("-", "_"),
        norm_pkg.replace("-", ""),
    }

    baseline_set = baseline_paths or set()
    for path in _iter_files(repo_root):
        rel = path.relative_to(repo_root).as_posix()
        if rel in baseline_set:
            continue
        rel_path = Path(rel)
        # Check if single-file module shadows dependency (e.g., pydantic.py)
        if rel_path.stem.lower() in candidate_names and rel_path.suffix.lower() == ".py":
            violations.append(
                GuardViolation(
                    path=rel,
                    kind="shadowing",
                    detail=f"Newly created file shadows upgraded package '{package_name}'",
                )
            )
        # Check if directory package shadows dependency (e.g., pydantic/__init__.py)
        elif len(rel_path.parts) > 1 and rel_path.parts[0].lower() in candidate_names:
            violations.append(
                GuardViolation(
                    path=rel,
                    kind="shadowing",
                    detail=f"Newly created package directory shadows upgraded package '{package_name}'",
                )
            )

    return violations


def compare_snapshots(
    baseline: TestSuiteSnapshot,
    repo_root: Path,
    *,
    package_name: str | None = None,
    baseline_result: PytestResult | None = None,
    current_result: PytestResult | None = None,
    masking_reference: PytestResult | None = None,
    masking_reference_label: str = "post-bump baseline",
    quarantined_paths: set[str] | Sequence[str] | None = None,
) -> GuardReport:
    """Re-hash the test surface and diff it against the baseline snapshot.

    Checks:
    - Test files modified, deleted, or added;
    - New conftest.py or pytest config files (pytest.ini, tox.ini, etc.);
    - Files or packages shadowing the upgraded dependency;
    - Newly skipped or xfailed tests compared to the masking reference.

    ``masking_reference`` is the run the skip/xfail profile is measured
    against: the old-pin GREEN run recorded before the bump. It falls back
    to ``baseline_result`` (the post-bump run) only when a caller has no
    pre-bump run at all, which is the pre-D1 behaviour.
    """
    violations: list[GuardViolation] = []
    baseline_by_path = {snapshot.path: snapshot for snapshot in baseline.files}
    current_paths: set[str] = set()
    quarantined_set = set(quarantined_paths or ())

    for path in test_files(repo_root):
        rel = path.relative_to(repo_root).as_posix()
        current_paths.add(rel)
        base = baseline_by_path.get(rel)
        if base is None:
            violations.append(
                GuardViolation(
                    path=rel,
                    kind="added",
                    detail="New test or configuration file added to test surface",
                )
            )
        elif _sha256(path) != base.sha256:
            violations.append(
                GuardViolation(
                    path=rel,
                    kind="modified",
                    detail="Existing test or configuration file modified",
                )
            )

    violations.extend(
        GuardViolation(
            path=rel,
            kind="deleted",
            detail="Existing test or configuration file deleted",
        )
        for rel in sorted(set(baseline_by_path) - current_paths - quarantined_set)
    )

    # Check package shadowing
    if package_name:
        baseline_set = (
            set(baseline.all_repo_files) if baseline.all_repo_files else set(baseline_by_path)
        )
        violations.extend(check_shadowing_files(repo_root, package_name, baseline_set))

    # Check newly skipped or xfailed tests. The reference is the old-pin
    # GREEN run when the caller has one: a post-bump run that never
    # collected has no meaningful skip/xfail profile.
    reference = masking_reference if masking_reference is not None else baseline_result
    if reference is not None and current_result is not None:
        violations.extend(
            check_skipped_or_xfailed(
                reference, current_result, reference_label=masking_reference_label
            )
        )

    violations.sort(key=lambda v: (v.path, v.kind))
    return GuardReport(
        clean=not violations,
        files_compared=len(current_paths),
        violations=violations,
    )


def guarded_status(status: VerifyStatus, report: GuardReport) -> VerifyStatus:
    """Fold a guard report into a verify status.

    Any test-surface violation wins over pytest's own verdict: a suite the
    agent edited cannot certify anything, so the run is ``CHEATED`` even if
    pytest itself passed.
    """
    if not report.clean:
        return VerifyStatus.CHEATED
    return status
