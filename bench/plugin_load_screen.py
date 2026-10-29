#!/usr/bin/env python
"""Screen pre-pytest-8 plugin releases for real breakage under a modern pytest.

Motivation: the rejected benchmark candidates were all cloned at ``HEAD``, where
plugin code already supports pytest 8, so "not reproduced" said nothing about
the releases that actually predate pytest 8. This screen installs one plugin
release at a time into a scratch venv alongside a modern pytest, then asks
pytest to collect a one-test file with the plugin enabled purely by its entry
point. A release whose hooks touch APIs removed in pytest 8 fails at load or
during collection, which is the failure a real repository sees after the bump.

Usage (from the repo root):
    python bench/plugin_load_screen.py --pytest-version 8.4.1 --out <path>

The run is read-only against the target repos: nothing is cloned, and the
scratch venv lives under ``bench/workdirs/`` (git-ignored).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import venv
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRATCH_ROOT = REPO_ROOT / "bench" / "workdirs" / "plugin-screen"

# (distribution, version) pairs that predate pytest 8 support.
CANDIDATES: tuple[tuple[str, str], ...] = (
    ("pytest-asyncio", "0.22.0"),
    ("pytest-asyncio", "0.21.1"),
    ("pytest-mock", "3.11.1"),
    ("pytest-html", "4.1.0"),
    ("pytest-order", "1.1.0"),
    ("pytest-timeout", "2.1.0"),
    ("pytest-sugar", "0.9.7"),
    ("pytest-randomly", "3.13.0"),
    ("pytest-rerunfailures", "11.1.2"),
    ("pytest-xdist", "3.3.1"),
    ("pytest-subtests", "0.11.0"),
)

_LOAD_FAILURE_MARKERS = (
    "PluginValidationError",
    "INTERNALERROR",
    "AttributeError",
    "ImportError",
    "ValueError: Plugin already registered",
)


def _venv_python(directory: Path) -> Path:
    return directory / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def _pip(python: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(python), "-m", "pip", "install", "--quiet", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pytest-version", default="8.4.1")
    parser.add_argument(
        "--python", default=sys.executable, help="interpreter for the scratch venv"
    )
    parser.add_argument("--out", help="also write the report to this path")
    args = parser.parse_args(argv)

    SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
    venv_dir = SCRATCH_ROOT / ".venv"
    if not venv_dir.is_dir():
        venv.create(venv_dir, with_pip=True)
    python = _venv_python(venv_dir)

    payload_dir = SCRATCH_ROOT / "payload"
    payload_dir.mkdir(parents=True, exist_ok=True)
    (payload_dir / "test_probe.py").write_text(
        "def test_probe() -> None:\n    assert True\n", encoding="utf-8"
    )

    lines: list[str] = []
    lines.append(f"python: {args.python}")
    lines.append(f"pytest target version: {args.pytest_version}")
    lines.append("")

    install = _pip(python, f"pytest=={args.pytest_version}")
    if install.returncode != 0:
        lines.append(f"could not install pytest {args.pytest_version}; aborting")
        print("\n".join(lines))
        return 1
    version = subprocess.run(
        [str(python), "-m", "pytest", "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).stdout.strip()
    lines.append(f"resolved: {version}")
    lines.append("")

    failures = 0
    for dist, version_pin in CANDIDATES:
        _pip(python, "uninstall", "--quiet", "--yes", dist)
        install = _pip(python, f"{dist}=={version_pin}")
        if install.returncode != 0:
            lines.append(f"{dist}=={version_pin}: INSTALL FAILED")
            failures += 1
            continue
        check = subprocess.run(
            [str(python), "-m", "pytest", "-q", "--collect-only", str(payload_dir)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        output = f"{check.stdout}\n{check.stderr}"
        marker = next((m for m in _LOAD_FAILURE_MARKERS if m in output), None)
        verdict = "LOADS" if check.returncode == 0 and marker is None else "BREAKS"
        if verdict == "BREAKS":
            failures += 1
        lines.append(f"{dist}=={version_pin}: {verdict} (exit {check.returncode})")
        if marker:
            offender = next((ln.strip() for ln in output.splitlines() if marker in ln), marker)
            lines.append(f"    {offender[:200]}")
        _pip(python, "uninstall", "--quiet", "--yes", dist)

    lines.append("")
    lines.append(
        f"summary: {failures}/{len(CANDIDATES)} pre-pytest-8 releases fail under "
        f"pytest {args.pytest_version}"
    )
    report = "\n".join(lines) + "\n"
    print(report)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
