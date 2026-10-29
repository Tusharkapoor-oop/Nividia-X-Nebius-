"""Offline tests for the held-out test split (Phase 3, OVERFIT detection).

The split is the mechanism that proves a patch generalises: files hashed into
the ``held_out`` set are never shown to the patch loop; ``heldout_status``
turns a GREEN-visible / non-GREEN-held-out outcome into ``OVERFIT``.

Pinned rules:
- deterministic and pure (same files + fraction ⇒ same split);
- disjoint, complete, and sorted;
- with >= 2 files both sides are non-empty; a lone file stays visible;
- the side decision keys on the repo-relative path, not absolute locations.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from upgradepilot.heldout import (
    DEFAULT_HELD_OUT_FRACTION,
    HeldOutSplit,
    HeldOutSplitError,
    heldout_status,
    split_test_files,
)
from upgradepilot.verify import VerifyStatus


def _write(root: Path, name: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("def test_x():\n    assert True\n", encoding="utf-8")
    return path


def _repo_files(root: Path, count: int, prefix: str = "tests") -> list[Path]:
    return [_write(root, f"{prefix}/test_{i}.py") for i in range(count)]


def test_split_is_deterministic(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    files = _repo_files(root, 10)
    assert split_test_files(files, root=root) == split_test_files(files, root=root)


def test_split_is_disjoint_complete_sorted(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    files = _repo_files(root, 8)
    split = split_test_files(files, root=root)
    expected = [f"tests/test_{i}.py" for i in range(8)]
    assert split.total == 8
    assert set(split.visible) | set(split.held_out) == set(expected)
    assert set(split.visible).isdisjoint(split.held_out)
    assert split.visible == sorted(split.visible)
    assert split.held_out == sorted(split.held_out)
    assert split.counts == (len(split.visible), len(split.held_out))


def test_many_files_keep_both_sides_non_empty(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    files = _repo_files(root, 40)
    split = split_test_files(files, root=root)
    assert split.visible and split.held_out
    assert split.total == 40


def test_single_file_stays_fully_visible(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    path = _write(root, "tests/test_app.py")
    split = split_test_files([path], root=root)
    assert split.visible == ["tests/test_app.py"]
    assert split.held_out == []


def test_empty_surface_is_an_empty_split(tmp_path: Path) -> None:
    split = split_test_files([], root=tmp_path / "repo")
    assert split.total == 0
    assert split.visible == []
    assert split.held_out == []


@pytest.mark.parametrize("fraction", [0.0, -0.1, 1.0, 1.5])
def test_invalid_fraction_raises(tmp_path: Path, fraction: float) -> None:
    root = tmp_path / "repo"
    path = _write(root, "tests/test_app.py")
    with pytest.raises(HeldOutSplitError):
        split_test_files([path], root=root, held_out_fraction=fraction)


def test_file_outside_root_raises(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    outside = _write(tmp_path, "elsewhere.py")
    with pytest.raises(HeldOutSplitError):
        split_test_files([outside], root=root)


def test_side_key_is_repo_relative_not_absolute(tmp_path: Path) -> None:
    """Two repos with identical relative layout split identically."""
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    files_a = _repo_files(root_a, 12)
    files_b = _repo_files(root_b, 12)
    split_a = split_test_files(files_a, root=root_a)
    split_b = split_test_files(files_b, root=root_b)
    assert split_a.visible == split_b.visible
    assert split_a.held_out == split_b.held_out


def test_json_roundtrip(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    split = split_test_files(_repo_files(root, 8), root=root)
    loaded = HeldOutSplit.model_validate_json(split.model_dump_json())
    assert loaded == split


def test_default_fraction_is_small() -> None:
    assert 0.0 < DEFAULT_HELD_OUT_FRACTION < 0.5


@pytest.mark.parametrize(
    ("visible", "heldout", "expected"),
    [
        (VerifyStatus.GREEN, VerifyStatus.GREEN, VerifyStatus.GREEN),
        (VerifyStatus.GREEN, VerifyStatus.STUCK, VerifyStatus.OVERFIT),
        (VerifyStatus.GREEN, VerifyStatus.ENV_FAIL, VerifyStatus.OVERFIT),
        (VerifyStatus.STUCK, VerifyStatus.GREEN, VerifyStatus.STUCK),
        (VerifyStatus.ENV_FAIL, VerifyStatus.STUCK, VerifyStatus.ENV_FAIL),
        (VerifyStatus.CHEATED, VerifyStatus.GREEN, VerifyStatus.CHEATED),
        (VerifyStatus.GREEN, VerifyStatus.CHEATED, VerifyStatus.CHEATED),
        (VerifyStatus.OVERFIT, VerifyStatus.GREEN, VerifyStatus.OVERFIT),
    ],
)
def test_heldout_status_table(
    visible: VerifyStatus,
    heldout: VerifyStatus,
    expected: VerifyStatus,
) -> None:
    assert heldout_status(visible, heldout) is expected


def test_quarantine_physically_moves_heldout_tests_outside_root(tmp_path: Path) -> None:
    """Held-out tests are physically removed from root and placed in quarantine_dir."""
    from upgradepilot.heldout import quarantine_heldout_tests, restore_heldout_tests

    root = tmp_path / "repo"
    _write(root, "src/pkg/app.py")
    files = _repo_files(root, 4)
    split = split_test_files(files, root=root)
    assert len(split.held_out) >= 1

    quarantine_dir = tmp_path / "quarantine"
    quarantined = quarantine_heldout_tests(root, split, quarantine_dir)

    assert set(quarantined) == set(split.held_out)
    for rel in split.held_out:
        assert not (root / rel).exists(), f"Held-out file {rel} still present in worktree!"
        assert (quarantine_dir / rel).is_file(), f"Held-out file {rel} missing from quarantine!"

    for rel in split.visible:
        assert (root / rel).is_file(), f"Visible file {rel} should remain in worktree!"

    # Restore moves them back
    restored = restore_heldout_tests(root, split, quarantine_dir)
    assert set(restored) == set(split.held_out)
    for rel in split.held_out:
        assert (root / rel).is_file(), f"Restored file {rel} missing from worktree!"


def test_agent_context_builder_cannot_see_quarantined_tests(tmp_path: Path) -> None:
    """Show that agent context builder and directory search cannot see quarantined files."""
    from upgradepilot.agent import list_source_files
    from upgradepilot.heldout import HeldOutQuarantine

    root = tmp_path / "repo"
    _write(root, "src/pkg/app.py")
    _write(root, "tests/test_visible.py")
    held_path = _write(root, "tests/test_secret_heldout.py")
    assert held_path.is_file()

    split = HeldOutSplit(
        held_out_fraction=0.5,
        total=2,
        visible=["tests/test_visible.py"],
        held_out=["tests/test_secret_heldout.py"],
    )
    quarantine_dir = tmp_path / "quarantine_outside"

    with HeldOutQuarantine(root, split, quarantine_dir):
        # 1. File physically absent from disk in the worktree
        assert not (root / "tests/test_secret_heldout.py").exists()

        # 2. Agent source crawler cannot see it
        sources = list_source_files(root)
        assert "tests/test_secret_heldout.py" not in sources

        # 3. Recursive directory walks inside the worktree cannot find it
        all_py = [p.relative_to(root).as_posix() for p in root.rglob("*.py")]
        assert "tests/test_secret_heldout.py" not in all_py
        assert "tests/test_visible.py" in all_py

    # Exiting context manager restores the files
    assert (root / "tests/test_secret_heldout.py").exists()


def test_single_test_repo_with_injected_behavioral_assertions(tmp_path: Path) -> None:
    """Repos with a single test file receive an injected behavioral held-out set."""
    from upgradepilot.heldout import inject_behavioral_assertions, quarantine_heldout_tests

    root = tmp_path / "repo"
    _write(root, "tests/test_lone.py")
    assert len(list(root.glob("tests/test_*.py"))) == 1

    # Injected behavioral assertion file
    code = "def test_behavior_one(): assert 1 == 1\n"
    injected_rel = inject_behavioral_assertions(root, code)
    assert injected_rel == "tests/test_heldout_behavioral.py"
    assert (root / injected_rel).is_file()

    # Now partition: lone file is visible, behavioral suite is held-out
    split = HeldOutSplit(
        held_out_fraction=0.5,
        total=2,
        visible=["tests/test_lone.py"],
        held_out=[injected_rel],
    )
    quarantine_dir = tmp_path / "quarantine"
    quarantine_heldout_tests(root, split, quarantine_dir)

    # During patching, lone file is visible, injected assertion file is quarantined
    assert (root / "tests/test_lone.py").is_file()
    assert not (root / injected_rel).exists()
    assert (quarantine_dir / injected_rel).is_file()
