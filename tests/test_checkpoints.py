"""Offline tests for checkpoint/rollback and verify_with_rollback (Phase 3).

``RepoCheckpoint`` guarantees a verify run can be wound back to a known
baseline; ``verify_with_rollback`` composes that with the verdict so only a
GREEN outcome leaves the tree in place.

Pinned rules:
- restore rewrites modified files, resurrects deleted ones, removes extras;
- restore is idempotent and never touches venv/git/cache metadata;
- non-GREEN outcomes roll back and record it; GREEN outcomes keep the tree.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from upgradepilot.checkpoints import RepoCheckpoint, snapshot_files
from upgradepilot.harness import RepoWorkdir, VenvInfo
from upgradepilot.models import PytestResult
from upgradepilot.run_ledger import RunLedger
from upgradepilot.verify import VerifyOutcome, VerifyStatus, verify_with_rollback


def _write(root: Path, rel: str, content: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    _write(root, "src/pkg/app.py", "def f():\n    return 1\n")
    _write(root, "tests/test_app.py", "def test_f():\n    assert f() == 1\n")
    _write(root, "pytest.ini", "[pytest]\n")
    return root


def _fake_repo(root: Path) -> RepoWorkdir:
    return RepoWorkdir(root=root, source="local", commit="fake")


def _fake_venv(root: Path) -> VenvInfo:
    return VenvInfo(directory=root / ".venv", python="python")


def _verify_mutator(
    root: Path,
    status: VerifyStatus,
    *,
    mutate: bool,
) -> Callable[..., VerifyOutcome]:
    """Fake verify that optionally mutates the tree, then returns ``status``."""

    def fake(
        repo: object,
        venv: object,
        timeout_s: float,
        *,
        ledger: RunLedger | None = None,
        label: str = "verify",
    ) -> VerifyOutcome:
        if mutate:
            (root / "src/pkg/app.py").write_text("def f():\n    return 999\n", encoding="utf-8")
            (root / "new_file.txt").write_text("side effect\n", encoding="utf-8")
        if ledger is not None:
            ledger.append(label, run_id="run-fake", status=status.value)
        return VerifyOutcome(
            status=status,
            run_id="run-fake",
            result=PytestResult(
                exit_code=0 if status is VerifyStatus.GREEN else 1,
                passed=2,
                failed=0 if status is VerifyStatus.GREEN else 1,
            ),
            reasons=[f"pytest exit: {status.value}"],
        )

    return fake


def test_restore_undoes_modify_add_delete(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    checkpoint = RepoCheckpoint.capture(root)
    _write(root, "src/pkg/app.py", "def f():\n    return 999\n")  # modify
    _write(root, "src/pkg/new.py", "NEW\n")  # add
    (root / "pytest.ini").unlink()  # delete
    restored = checkpoint.restore(root)
    assert (root / "src/pkg/app.py").read_text(encoding="utf-8") == "def f():\n    return 1\n"
    assert not (root / "src/pkg/new.py").exists()
    assert (root / "pytest.ini").exists()
    assert restored >= 3


def test_restore_is_idempotent(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    checkpoint = RepoCheckpoint.capture(root)
    assert checkpoint.restore(root) == 0
    assert checkpoint.restore(root) == 0


def test_snapshot_skips_metadata_dirs(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    _write(root, ".venv/Lib/site-packages/test_evil.py", "evil\n")
    _write(root, ".git/hooks/test_hook.py", "#\n")
    _write(root, "src/pkg/__pycache__/c.pyc", "\x00")
    _write(root, "src/pkg.egg-info/PKG-INFO", "meta\n")
    snapshot = snapshot_files(root)
    rels = set(snapshot)
    assert "src/pkg/app.py" in rels
    assert not any(r.startswith(".venv") for r in rels)
    assert not any(r.startswith(".git") for r in rels)
    assert not any(".egg-info" in r for r in rels)
    assert not any("__pycache__" in r for r in rels)


def test_rollback_happens_when_not_green(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    fake = _verify_mutator(root, VerifyStatus.STUCK, mutate=True)
    outcome = verify_with_rollback(_fake_repo(root), _fake_venv(root), 60.0, verify_fn=fake)
    assert outcome.status is VerifyStatus.STUCK
    # The patch mutation and the run side-effect are both wound back.
    assert (root / "src/pkg/app.py").read_text(encoding="utf-8") == "def f():\n    return 1\n"
    assert not (root / "new_file.txt").exists()
    assert any("rollback" in reason for reason in outcome.reasons)


def test_green_keeps_changes(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    fake = _verify_mutator(root, VerifyStatus.GREEN, mutate=True)
    outcome = verify_with_rollback(_fake_repo(root), _fake_venv(root), 60.0, verify_fn=fake)
    assert outcome.status is VerifyStatus.GREEN
    assert (root / "src/pkg/app.py").read_text(encoding="utf-8") == "def f():\n    return 999\n"
    assert (root / "new_file.txt").exists()


def test_rollback_is_recorded_in_ledger(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    ledger = RunLedger(tmp_path / "ledger")
    fake = _verify_mutator(root, VerifyStatus.ENV_FAIL, mutate=True)
    outcome = verify_with_rollback(
        _fake_repo(root), _fake_venv(root), 60.0, ledger=ledger, verify_fn=fake
    )
    assert outcome.status is VerifyStatus.ENV_FAIL
    events = ledger.read_all()
    assert [e.event for e in events] == ["verify", "rollback"]
    assert events[1].data["status"] == "ROLLED_BACK"
    assert events[1].data["restored_files"] >= 2
