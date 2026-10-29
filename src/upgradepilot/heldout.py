"""Held-out test split: the mechanism for OVERFIT detection (Phase 3).

The agent may only see the *visible* test surface while patching. A held-out
subset of tests stays out of the patch loop and is run only at certification.
If the patch passes the visible tests but fails the held-out ones, the run is
``OVERFIT``: the patch was tuned to the visible tests instead of proving
itself against the real suite.

Design rules:

- deterministic: ``sha256`` of the repo-relative path decides the side, so
  the same files partition identically on every run and machine;
- pure: the split is a function of ``(files, held_out_fraction)`` only, with
  no hidden randomness;
- non-degenerate: with >= 2 test files the split always keeps at least one
  file on each side; a single-file surface stays fully visible (there is
  nothing to hold out) and is documented as such;
- fraction is small by default (0.25) so the patch loop still exercises most
  of the suite while certification keeps enough held-out evidence.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from upgradepilot.verify import VerifyStatus

# Default share of the test surface kept out of the patch loop.
DEFAULT_HELD_OUT_FRACTION = 0.25


class HeldOutSplitError(RuntimeError):
    """A held-out split could not be built from the given test surface."""


class HeldOutSplit(BaseModel):
    """A deterministic, disjoint partition of the test surface."""

    method: Literal["sha256-path"] = "sha256-path"
    held_out_fraction: float
    total: int = 0
    visible: list[str] = Field(default_factory=list)
    held_out: list[str] = Field(default_factory=list)

    @property
    def counts(self) -> tuple[int, int]:
        """(visible, held_out) counts for summary output."""
        return len(self.visible), len(self.held_out)


def _side_key(rel: str) -> int:
    """First 16 bits of the path hash, used as the [0, 65536) bucket."""
    return int.from_bytes(hashlib.sha256(rel.encode("utf-8")).digest()[:2], "big")


def split_test_files(
    files: Sequence[Path],
    *,
    root: Path,
    held_out_fraction: float = DEFAULT_HELD_OUT_FRACTION,
) -> HeldOutSplit:
    """Split a repo's test files into visible and held-out halves.

    Args:
        files: Test-surface paths (absolute, or repo-root-relative).
        root: The repo root those files belong to; membership is enforced
            so a stray absolute path cannot silently join the split.
        held_out_fraction: Share of files to keep hidden from the patch
            loop, in the exclusive range ``(0, 1)``.

    Raises:
        HeldOutSplitError: invalid fraction, or any file outside ``root``.
    """
    if not 0.0 < held_out_fraction < 1.0:
        raise HeldOutSplitError(f"held_out_fraction must be in (0, 1), got {held_out_fraction!r}")

    root = root.absolute()
    rels: list[str] = []
    for path in files:
        candidate = path if path.is_absolute() else root / path
        try:
            rel = candidate.relative_to(root).as_posix()
        except ValueError as exc:
            raise HeldOutSplitError(f"{candidate} is not inside repo root {root}") from exc
        rels.append(rel)
    rels.sort()

    visible: list[str] = []
    held_out: list[str] = []
    for rel in rels:
        if _side_key(rel) / 65536 < held_out_fraction:
            held_out.append(rel)
        else:
            visible.append(rel)

    # Degenerate-split repair: never leave either side empty when there is
    # more than one file, and never move a lone file into held-out.
    if not held_out and len(visible) > 1:
        held_out.append(visible.pop())
    if not visible and held_out:
        visible.append(held_out.pop())
    held_out.sort()
    visible.sort()

    return HeldOutSplit(
        held_out_fraction=held_out_fraction,
        total=len(rels),
        visible=visible,
        held_out=held_out,
    )


def heldout_status(visible: VerifyStatus, heldout: VerifyStatus) -> VerifyStatus:
    """Fold the held-out verdict into the run's final status.

    Rules:
    - ``CHEATED`` (guard) wins over everything on either side;
    - a non-GREEN visible verdict stands on its own (the run already failed
      before held-out evidence was meaningful);
    - a GREEN visible verdict *and* a GREEN held-out verdict certify GREEN;
    - GREEN visible but a failing held-out verdict is ``OVERFIT``.
    """
    if VerifyStatus.CHEATED in (visible, heldout):
        return VerifyStatus.CHEATED
    if visible is not VerifyStatus.GREEN:
        return visible
    if heldout is VerifyStatus.GREEN:
        return VerifyStatus.GREEN
    return VerifyStatus.OVERFIT


def quarantine_heldout_tests(
    root: Path,
    split: HeldOutSplit,
    quarantine_dir: Path,
) -> list[str]:
    """Physically move held-out test files from repo root to quarantine_dir.

    The files are moved out of the worktree completely so that no agent context
    builder, file scanner, or test runner can see or read them during patching.

    Args:
        root: The repository root where test files live.
        split: The HeldOutSplit containing paths in split.held_out.
        quarantine_dir: An external directory outside the worktree.

    Returns:
        List of relative paths successfully quarantined.
    """
    import shutil

    root = root.resolve()
    quarantine_dir = quarantine_dir.resolve()
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    quarantined: list[str] = []

    for rel in split.held_out:
        src = root / rel
        if src.is_file():
            dest = quarantine_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
            quarantined.append(rel)
    return quarantined


def restore_heldout_tests(
    root: Path,
    split: HeldOutSplit,
    quarantine_dir: Path,
) -> list[str]:
    """Restore quarantined held-out test files back into the repo root.

    Invoked immediately before the final certification verify step.

    Args:
        root: The repository root to restore into.
        split: The HeldOutSplit containing paths in split.held_out.
        quarantine_dir: The external quarantine directory holding the files.

    Returns:
        List of relative paths successfully restored.
    """
    import shutil

    root = root.resolve()
    quarantine_dir = quarantine_dir.resolve()
    restored: list[str] = []

    for rel in split.held_out:
        src = quarantine_dir / rel
        if src.is_file():
            dest = root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))
            restored.append(rel)
    return restored


class HeldOutQuarantine:
    """Context manager ensuring held-out tests are quarantined during patching

    and safely restored at certification or on error/exit.
    """

    def __init__(self, root: Path, split: HeldOutSplit, quarantine_dir: Path) -> None:
        self.root = root.resolve()
        self.split = split
        self.quarantine_dir = quarantine_dir.resolve()
        self.is_quarantined = False

    def quarantine(self) -> list[str]:
        if not self.is_quarantined and self.split.held_out:
            quarantined = quarantine_heldout_tests(self.root, self.split, self.quarantine_dir)
            self.is_quarantined = True
            return quarantined
        return []

    def restore(self) -> list[str]:
        if self.is_quarantined:
            restored = restore_heldout_tests(self.root, self.split, self.quarantine_dir)
            self.is_quarantined = False
            return restored
        return []

    def __enter__(self) -> HeldOutQuarantine:
        self.quarantine()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object | None,
    ) -> None:
        self.restore()


def inject_behavioral_assertions(
    root: Path,
    assertions_code: str,
    target_rel: str = "tests/test_heldout_behavioral.py",
) -> str:
    """Inject external behavioral assertions into a repo to establish a held-out set.

    Essential for single-test-file repositories where an internal partition is
    impossible without hiding the entire test surface.

    Args:
        root: Repo root directory.
        assertions_code: Python test module code containing behavioral assertions.
        target_rel: Relative destination within the repo (defaults to
            tests/test_heldout_behavioral.py).

    Returns:
        The relative posix path to the newly injected assertion file.
    """
    root = root.resolve()
    target = root / target_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(assertions_code, encoding="utf-8")
    return target.relative_to(root).as_posix()
