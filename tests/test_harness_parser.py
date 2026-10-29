"""Pure unit tests for pytest summary parsing (no subprocess)."""

from __future__ import annotations

from pathlib import Path

from upgradepilot.harness import config_isolation_args, parse_pytest_summary


def test_parse_basic_pass() -> None:
    out = "....\n5 passed in 0.42s\n"
    r = parse_pytest_summary(out, exit_code=0)
    assert r.passed == 5
    assert r.failed == 0
    assert r.duration_s == 0.42
    assert r.ok


def test_parse_mixed_counts() -> None:
    out = "...\n2 failed, 3 passed, 1 error in 1.60s\n"
    r = parse_pytest_summary(out, exit_code=1)
    assert r.failed == 2
    assert r.passed == 3
    assert r.errors == 1
    assert not r.ok
    assert r.duration_s == 1.60


def test_parse_warnings_and_xfailing() -> None:
    out = "...\n10 passed, 2 xfailed, 1 xpassed, 3 skipped, 5 warnings in 3.10s\n"
    r = parse_pytest_summary(out, exit_code=0)
    assert r.passed == 10
    assert r.xfailed == 2
    assert r.xpassed == 1
    assert r.skipped == 3
    assert r.duration_s == 3.10


def test_no_summary_is_not_fabricated() -> None:
    out = "usage: pytest [options] [file_or_dir]\npytest: error: argument --x: expected one argument\n"
    r = parse_pytest_summary(out, exit_code=4)
    assert r.passed == 0
    assert r.failed == 0
    assert not r.collected_anything
    assert not r.ok


def test_collect_errors_are_errors() -> None:
    out = "...\n4 errors in 0.90s\n"
    r = parse_pytest_summary(out, exit_code=2)
    assert r.errors == 4
    assert r.failed == 0


def test_config_isolation_pins_rootdir_with_generated_config(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    venv = tmp_path / "venv"
    venv.mkdir()

    args = config_isolation_args(repo, venv)

    assert args[:2] == ["-c", str(venv.resolve() / ".upgradepilot-empty-pytest.ini")]
    assert args[2:] == ["--rootdir", str(repo.resolve())]
    assert (venv / ".upgradepilot-empty-pytest.ini").is_file()


def test_config_isolation_pins_rootdir_with_repo_config(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\nminversion = '7.0'\n",
        encoding="utf-8",
    )
    venv = tmp_path / "venv"
    venv.mkdir()

    args = config_isolation_args(repo, venv)

    assert args == [
        "-c",
        str(repo.resolve() / "pyproject.toml"),
        "--rootdir",
        str(repo.resolve()),
    ]
