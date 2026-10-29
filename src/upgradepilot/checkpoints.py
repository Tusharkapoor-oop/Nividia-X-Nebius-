"""Checkpoint/rollback for the verify step (Phase 3).

``RepoCheckpoint`` snapshots the target repo's working tree byte-for-byte
(excluding VCS, venv, and cache metadata) so a verify run can always be
wound back to a known baseline. ``verify_with_rollback`` (in
``upgradepilot.verify``) uses it to guarantee that only a ``GREEN`` outcome
leaves the tree in place: any other outcome restores the snapshot, so no
partial patch, test side-effect, or generated file can leak into the next
iteration of the agent loop.

Trust rules mirror the harness: no shell, pure path operations, and a skip
list shared with the guard so third-party dependency trees are never walked.
"""

from __future__ import annotations

from pathlib import Path

from upgradepilot.guard import SKIP_DIRS

_EGG_INFO_SUFFIX = ".egg-info"


def _is_skipped_part(part: str) -> bool:
    return part in SKIP_DIRS or part.endswith(_EGG_INFO_SUFFIX)


def snapshot_files(root: Path) -> dict[str, bytes]:
    """Map repo-relative posix paths to raw bytes for every file.

    Metadata directories (``.git``, venvs, caches, builds, ``*.egg-info``)
    are excluded so a checkpoint never needs to fingerprint a dependency
    tree or repo history; rollback therefore cannot touch them.
    """
    files: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(_is_skipped_part(part) for part in rel.parts):
            continue
        if path.is_file():
            files[rel.as_posix()] = path.read_bytes()
    return files


class RepoCheckpoint:
    """Byte-level snapshot of a repo's working tree minus metadata dirs."""

    def __init__(self, root: Path, files: dict[str, bytes]) -> None:
        self.root = Path(root)
        self._files = dict(files)

    @classmethod
    def capture(cls, root: Path) -> RepoCheckpoint:
        """Snapshot ``root`` now; call :meth:`restore` to return to it."""
        root = Path(root)
        return cls(root=root, files=snapshot_files(root))

    def restore(self, root: Path | None = None) -> int:
        """Restore the tree captured at :meth:`capture`.

        Rewrites every file whose bytes differ, recreates deleted files, and
        deletes files that did not exist at capture time.

        Returns:
            The number of paths actually rewritten or removed.
        """
        target = Path(root) if root is not None else self.root
        restored = 0
        for rel, content in self._files.items():
            dest = target / rel
            if not dest.exists() or dest.read_bytes() != content:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(content)
                restored += 1
        for rel in snapshot_files(target):
            if rel not in self._files:
                (target / rel).unlink()
                restored += 1
        return restored
