"""LLM edit protocol and safe application (Phase 4).

The patch model never touches the filesystem directly: it answers with a JSON
payload describing file edits, and this module validates and applies them.

Trust boundaries:
- paths must stay inside the repo root (no absolute paths, no ``..``);
- paths inside the guarded test surface (``test_*.py``, ``*_test.py``,
  ``conftest.py``, pytest config files) are refused — the proof card for a
  run must never contain an edit the guard would call ``CHEATED``;
- every applied edit records a unified diff, but no edit is ever applied
  without first surviving :func:`validate_edits`.
"""

from __future__ import annotations

import difflib
import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from upgradepilot.guard import GUARDED_CONFIG_NAMES, SKIP_DIRS, TEST_FILE_NAMES

# The agent may only repair application source. Metadata directories and
# non-Python files are not patch targets; treating them as off-limits keeps a
# model from "fixing" the harness, dependency metadata, or recorded evidence.
_PROTECTED_DIRS = frozenset(SKIP_DIRS | {"artifacts", "tests", "test"})
_EDITABLE_SUFFIXES = frozenset({".py", ".pyi"})

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class EditError(RuntimeError):
    """An edit payload is unusable: unparsable, escaping, or guarded."""


class PatchEdit(BaseModel):
    """One requested file operation: write full content or delete the file."""

    path: str
    action: Literal["write", "delete"] = "write"
    content: str = ""


class EditsPayload(BaseModel):
    """The only shape the patch model may use to change files."""

    files: list[PatchEdit] = Field(default_factory=list)


class EditApplied(BaseModel):
    """Evidence for one applied edit: path, action, and unified diff."""

    path: str
    action: Literal["write", "delete"]
    diff: str = ""


def _find_balanced(text: str, start: int, opener: str = "{", closer: str = "}") -> int:
    """Index of the closing brace matching the opener at ``start``.

    Tracks string literals so braces inside JSON values do not count.
    """
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return index
    return -1


def extract_json_object(content: str) -> dict[str, Any] | None:
    """Pull the first complete JSON object out of the model's answer.

    Handles `` ```json ``-fenced blocks first, then falls back to scanning
    for the first balanced ``{…}`` in the raw text.
    """
    text = content.strip()
    fenced = _FENCE_RE.search(text)
    if fenced is not None:
        try:
            value = json.loads(fenced.group(1).strip())
        except json.JSONDecodeError:
            value = None
        if isinstance(value, dict):
            return value
    start = text.find("{")
    while start != -1:
        end = _find_balanced(text, start)
        if end == -1:
            return None
        try:
            value = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            start = text.find("{", start + 1)
            continue
        return value if isinstance(value, dict) else None
    return None


def _is_guarded_path(rel: Path) -> bool:
    if rel.name in GUARDED_CONFIG_NAMES:
        return True
    return any(rel.match(pattern) for pattern in TEST_FILE_NAMES)


def _is_protected_path(rel: Path) -> bool:
    if any(part in _PROTECTED_DIRS for part in rel.parts):
        return True
    return rel.suffix.lower() not in _EDITABLE_SUFFIXES


def validate_edits(edits: list[PatchEdit], root: Path) -> list[PatchEdit]:
    """Return ``edits`` unchanged after every path passes the trust checks.

    Raises:
        EditError: an edit escapes the repo root, targets the guarded test
            surface (test files, conftest, pytest config), targets a
            protected metadata directory, or is not Python source.
    """
    root = root.absolute()
    for edit in edits:
        if not edit.path.strip():
            raise EditError("edit path must not be empty")
        rel = Path(edit.path.replace("\\", "/"))
        if rel.is_absolute() or edit.path.startswith(("/", "\\")):
            raise EditError(f"edit path must be repo-relative, got {edit.path!r}")
        if any(part == ".." for part in rel.parts):
            raise EditError(f"edit path escapes repo root: {edit.path!r}")
        dest = (root / rel).resolve()
        try:
            dest.relative_to(root)
        except ValueError as exc:
            raise EditError(f"edit path escapes repo root: {edit.path!r}") from exc
        if _is_guarded_path(rel):
            raise EditError(f"edit targets the guarded test surface: {edit.path!r}")
        if _is_protected_path(rel):
            raise EditError(f"edit targets a protected non-source path: {edit.path!r}")
    return edits


def apply_edits(root: Path, edits: list[PatchEdit]) -> list[EditApplied]:
    """Validate and apply edits, returning per-file diff evidence.

    Raises:
        EditError: carry-over from :func:`validate_edits`; nothing is applied
            if any edit fails validation.
    """
    validated = validate_edits(edits, root)
    root = root.absolute()
    applied: list[EditApplied] = []
    for edit in validated:
        dest = root / Path(edit.path.replace("\\", "/"))
        before = dest.read_text(encoding="utf-8", errors="replace") if dest.exists() else ""
        if edit.action == "delete":
            if dest.exists():
                dest.unlink()
            after: str = ""
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(edit.content, encoding="utf-8")
            after = edit.content
        diff = "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile="a/" + edit.path,
                tofile="b/" + edit.path,
            )
        )
        applied.append(EditApplied(path=edit.path, action=edit.action, diff=diff))
    return applied
