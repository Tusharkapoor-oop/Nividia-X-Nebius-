"""Offline unit tests for editing protocol and safe patch application (Phase 4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from upgradepilot.editing import (
    EditError,
    EditsPayload,
    PatchEdit,
    apply_edits,
    extract_json_object,
    validate_edits,
)


def test_extract_json_object_fenced() -> None:
    text = """Here is the fix:
```json
{
  "files": [
    {
      "path": "src/app.py",
      "action": "write",
      "content": "print('hello')\\n"
    }
  ]
}
```
Hope this helps!
"""
    obj = extract_json_object(text)
    assert obj is not None
    payload = EditsPayload.model_validate(obj)
    assert len(payload.files) == 1
    assert payload.files[0].path == "src/app.py"
    assert payload.files[0].content == "print('hello')\n"


def test_extract_json_object_raw_balanced() -> None:
    text = """I will apply this change:
{"files": [{"path": "pkg/mod.py", "action": "write", "content": "x = 1"}]}
Done."""
    obj = extract_json_object(text)
    assert obj is not None
    assert "files" in obj
    assert obj["files"][0]["path"] == "pkg/mod.py"


def test_extract_json_object_unbalanced_returns_none() -> None:
    text = 'Here is an unclosed json: {"files": [1, 2'
    assert extract_json_object(text) is None


def test_validate_edits_allows_normal_source(tmp_path: Path) -> None:
    edits = [
        PatchEdit(path="src/pkg/main.py", action="write", content="a = 1\n"),
        PatchEdit(path="old_file.py", action="delete"),
    ]
    validated = validate_edits(edits, tmp_path)
    assert len(validated) == 2


def test_validate_edits_rejects_absolute_path(tmp_path: Path) -> None:
    edits = [PatchEdit(path="/etc/passwd", action="write", content="")]
    with pytest.raises(EditError, match="must be repo-relative"):
        validate_edits(edits, tmp_path)


def test_validate_edits_rejects_escaping_path(tmp_path: Path) -> None:
    edits = [PatchEdit(path="../outside.py", action="write", content="")]
    with pytest.raises(EditError, match="escapes repo root"):
        validate_edits(edits, tmp_path)


@pytest.mark.parametrize(
    "guarded_path",
    [
        "tests/test_something.py",
        "tests/something_test.py",
        "conftest.py",
        "tests/conftest.py",
        "pytest.ini",
        "tox.ini",
        "setup.cfg",
        "pyproject.toml",
        "tests\\test_something.py",
    ],
)
def test_validate_edits_rejects_guarded_test_surface(tmp_path: Path, guarded_path: str) -> None:
    edits = [PatchEdit(path=guarded_path, action="write", content="# hacked")]
    with pytest.raises(EditError, match="targets the guarded test surface"):
        validate_edits(edits, tmp_path)


@pytest.mark.parametrize(
    "protected_path",
    [
        "tests/helpers.py",
        ".upv-venv/Lib/site-packages/pkg/mod.py",
        ".git/hooks/helper.py",
        "README.md",
        "pyproject.toml",
    ],
)
def test_validate_edits_rejects_protected_paths(tmp_path: Path, protected_path: str) -> None:
    edits = [PatchEdit(path=protected_path, action="write", content="# hacked")]
    with pytest.raises(EditError, match=r"guarded test surface|protected non-source"):
        validate_edits(edits, tmp_path)


def test_validate_edits_rejects_empty_path(tmp_path: Path) -> None:
    edits = [PatchEdit(path="  ", action="write", content="x = 1\n")]
    with pytest.raises(EditError, match="must not be empty"):
        validate_edits(edits, tmp_path)


def test_apply_edits_refuses_guarded_before_writing(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    target = tests_dir / "test_app.py"
    target.write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    edits = [
        PatchEdit(path="tests/test_app.py", action="write", content="def test_ok():\n    pass\n")
    ]

    with pytest.raises(EditError, match="guarded test surface"):
        apply_edits(tmp_path, edits)

    assert target.read_text(encoding="utf-8") == "def test_ok():\n    assert True\n"


def test_apply_edits_writes_file_and_emits_diff(tmp_path: Path) -> None:
    target = tmp_path / "src" / "math.py"
    target.parent.mkdir(parents=True)
    target.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")

    edits = [
        PatchEdit(
            path="src/math.py",
            action="write",
            content="def add(a, b):\n    return a + b\n",
        )
    ]
    applied = apply_edits(tmp_path, edits)
    assert len(applied) == 1
    assert applied[0].path == "src/math.py"
    assert applied[0].action == "write"
    assert "-    return a - b" in applied[0].diff
    assert "+    return a + b" in applied[0].diff
    assert target.read_text(encoding="utf-8") == "def add(a, b):\n    return a + b\n"


def test_apply_edits_creates_new_file(tmp_path: Path) -> None:
    edits = [
        PatchEdit(
            path="src/new_mod.py",
            action="write",
            content="CONSTANT = 42\n",
        )
    ]
    applied = apply_edits(tmp_path, edits)
    assert len(applied) == 1
    assert (tmp_path / "src" / "new_mod.py").is_file()
    assert (tmp_path / "src" / "new_mod.py").read_text(encoding="utf-8") == "CONSTANT = 42\n"


def test_apply_edits_deletes_file(tmp_path: Path) -> None:
    target = tmp_path / "temp.py"
    target.write_text("trash", encoding="utf-8")

    edits = [PatchEdit(path="temp.py", action="delete")]
    applied = apply_edits(tmp_path, edits)
    assert len(applied) == 1
    assert applied[0].action == "delete"
    assert not target.exists()
