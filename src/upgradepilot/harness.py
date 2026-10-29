"""Harness: clone a repo at a pinned commit, build a venv, run pytest.

Trust boundary rules baked in here:
- never ``shell=True``; every subprocess is an argv list with a timeout;
- never touch the user's test files; the harness only *executes* pytest;
- a timeout kills the process **tree** (taskkill on Windows, killpg on
  POSIX) so runaway target tests cannot outlive the pipeline;
- pytest output is parsed from pytest's own summary line, not invented.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from upgradepilot.models import PytestResult

_GIT_TIMEOUT_S = 300.0
_VENV_MAKE_TIMEOUT_S = 600.0
_DEFAULT_PYTEST_TIMEOUT_S = 300.0


class HarnessError(RuntimeError):
    """A setup/verification step failed; message is safe to surface."""


@dataclass(frozen=True)
class RepoWorkdir:
    """A prepared, pinned checkout inside our own workspace."""

    root: Path
    source: str
    commit: str


@dataclass(frozen=True)
class VenvInfo:
    """Paths of the venv built for a target repo."""

    directory: Path
    python: str

    @property
    def bin_dir(self) -> Path:
        return self.directory / ("Scripts" if os.name == "nt" else "bin")


def _run(
    argv: list[str], *, cwd: Path | None = None, timeout_s: float
) -> subprocess.CompletedProcess[str]:
    """Run argv without shell, with hard timeout and tree cleanup."""
    argv_list = [str(a) for a in argv]
    cwd_str = str(cwd) if cwd is not None else None
    popen: subprocess.Popen[str] | None = None
    try:
        popen = subprocess.Popen(
            argv_list,
            cwd=cwd_str,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:
        raise HarnessError(f"executable not found: {argv_list[0]}") from exc

    try:
        completed = popen.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        _tree_kill(popen.pid)
        raise HarnessError(
            f"timeout after {timeout_s:.0f}s: {Path(argv_list[0]).name} "
            f"{' '.join(_short(argv_list[1:]))}"
        ) from exc

    return subprocess.CompletedProcess(
        args=argv_list,
        returncode=poll_process_exit(popen),
        stdout=completed[0] or "",
        stderr=completed[1] or "",
    )


def poll_process_exit(process: subprocess.Popen[str]) -> int:
    """Read the exit code after communicate(); -1 if the pipe closed oddly."""
    return process.returncode if process.returncode is not None else -1


def _short(argv: list[str]) -> list[str]:
    return [a if len(a) <= 80 else a[:77] + "..." for a in argv]


def _tree_kill(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            check=False,
            timeout=15,
        )
    else:
        import contextlib
        import signal

        # mypy: killpg/getpgid/SIGKILL are POSIX-only; guarded by os.name.
        killpg: Any = os.killpg  # type: ignore[attr-defined]
        getpgid: Any = os.getpgid  # type: ignore[attr-defined]
        sigkill: Any = signal.SIGKILL  # type: ignore[attr-defined]
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            killpg(getpgid(pid), sigkill)


def _git(argv: list[str], *, cwd: Path | None = None) -> str:
    completed = _run(["git", *argv], cwd=cwd, timeout_s=_GIT_TIMEOUT_S)
    if completed.returncode != 0:
        raise HarnessError(
            f"git {' '.join(argv)} failed (rc={completed.returncode}): "
            f"{(completed.stderr or completed.stdout).strip()[:400]}"
        )
    return completed.stdout.strip()


def clone_pinned(
    source: str,
    commit: str,
    workdirs_root: Path,
    *,
    name: str | None = None,
) -> RepoWorkdir:
    """Clone ``source`` into ``workdirs_root``, then detach at ``commit``.

    ``source`` is either a git URL or a local path to a git repo. The commit
    may be a full or short SHA, a tag, or "HEAD".
    """
    src = Path(source).expanduser()
    is_local = src.exists()
    if not is_local and not source.startswith(("http://", "https://", "git@", "ssh://")):
        raise HarnessError(f"source must be a local path or git URL, got {source!r}")

    default_name = src.name if is_local else source.rstrip("/").split("/")[-1].removesuffix(".git")
    if not default_name:
        raise HarnessError(f"cannot derive directory name from {source!r}")
    target_root = workdirs_root / (name or default_name)

    workdirs_root.mkdir(parents=True, exist_ok=True)
    if target_root.exists():
        raise HarnessError(f"workdir already exists: {target_root}")

    _git(["clone", "--quiet", source, str(target_root)])
    _git(["checkout", "--quiet", "--detach", commit], cwd=target_root)
    resolved = _git(["rev-parse", "HEAD"], cwd=target_root)
    return RepoWorkdir(root=target_root, source=source, commit=resolved)


def make_pinned_venv(repo_root: Path, *, venv_name: str = ".upv-venv") -> VenvInfo:
    """Create a dedicated venv inside the target checkout.

    Any previous ``<venv_name>`` is deleted first so a run is always from a
    clean, reproducible install.
    """
    venv_dir = repo_root / venv_name
    if venv_dir.exists():
        import shutil

        shutil.rmtree(venv_dir)
    _run([sys.executable, "-m", "venv", str(venv_dir)], timeout_s=_VENV_MAKE_TIMEOUT_S)
    python = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.exists():
        raise HarnessError(f"venv python missing after creation: {python}")
    return VenvInfo(directory=venv_dir, python=str(python))


def pip_install(venv: VenvInfo, *pip_args: str, timeout_s: float = 600.0) -> str:
    """pip install inside the venv; returns stdout tail for the record."""
    completed = _run(
        [venv.python, "-m", "pip", "install", "--quiet", *pip_args],
        cwd=venv.directory.parent,
        timeout_s=timeout_s,
    )
    if completed.returncode != 0:
        tail = (completed.stderr or completed.stdout).strip()[-600:]
        raise HarnessError(f"pip install failed (rc={completed.returncode}): {tail}")
    return completed.stdout.strip()[-400:]


def resolved_versions(venv: VenvInfo, *packages: str) -> dict[str, str]:
    """Interpreter and installed-package versions, read from the venv itself.

    Uses ``importlib.metadata`` inside the target venv, so the record states
    what is actually installed rather than what a requirements file asked
    for. ``pytest`` is always recorded. A read failure is reported in an
    ``error`` key instead of raising: version evidence must never be the
    reason a run aborts, but it must also never be silently omitted.
    """
    names = ["pytest", *packages]
    script = (
        "import json, sys\n"
        "from importlib import metadata\n"
        f"names = {names!r}\n"
        "out = {'python': sys.version.split()[0]}\n"
        "for name in names:\n"
        "    try:\n"
        "        out[name] = metadata.version(name)\n"
        "    except metadata.PackageNotFoundError:\n"
        "        out[name] = 'not-installed'\n"
        "print(json.dumps(out, sort_keys=True))\n"
    )
    completed = _run([venv.python, "-c", script], timeout_s=120.0)
    if completed.returncode != 0:
        tail = (completed.stderr or completed.stdout).strip()[:300]
        return {"python": "", "error": tail}
    try:
        parsed = json.loads(completed.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"python": "", "error": "unparseable version output"}
    if not isinstance(parsed, dict):  # defensive: a list here is a bug, not data
        return {"python": "", "error": "unexpected version payload"}
    return {str(key): str(value) for key, value in parsed.items()}


_CONFIG_CANDIDATES: tuple[tuple[str, str], ...] = (
    # (file name, marker section text that makes it a pytest config)
    # Same precedence order pytest itself uses during discovery.
    ("pytest.ini", "[pytest]"),
    ("pyproject.toml", "[tool.pytest.ini_options]"),
    ("tox.ini", "[pytest]"),
    ("setup.cfg", "[tool:pytest]"),
)


def config_isolation_args(repo_root: Path, venv_dir: Path) -> list[str]:
    """Args that pin the child pytest to exactly one config file.

    If the target repo declares its own pytest config at its root, that file
    is honoured (realistic environment). Otherwise a minimal empty config is
    generated inside the target's venv so pytest cannot walk up into our own
    (or any other ancestor) configuration.

    The explicit ``--rootdir`` matters: pytest otherwise derives rootdir from
    the ``-c`` file's directory. For the generated config that directory is
    inside the venv, which makes node IDs and relative test paths wrong.
    """
    repo_root = repo_root.resolve()
    venv_dir = venv_dir.resolve()
    for name, marker in _CONFIG_CANDIDATES:
        candidate = repo_root / name
        if not candidate.is_file():
            continue
        try:
            text = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if marker in text:
            return ["-c", str(candidate), "--rootdir", str(repo_root)]
    empty = venv_dir / ".upgradepilot-empty-pytest.ini"
    empty.write_text("[pytest]\n", encoding="utf-8")
    return ["-c", str(empty), "--rootdir", str(repo_root)]


def run_pytest(
    venv: VenvInfo,
    repo_root: Path,
    *,
    timeout_s: float = _DEFAULT_PYTEST_TIMEOUT_S,
    extra_args: list[str] | None = None,
) -> PytestResult:
    """Run pytest in the target repo with the venv's python and parse it.

    The child run is isolated from configuration files that happen to sit in
    ancestor directories (e.g. this repo's own ``pyproject.toml`` when a
    workdir is nested inside it): pytest would otherwise climb up from the
    target and load them.
    """
    # No ``-q`` here on purpose: a target may already pass ``-q`` in its own
    # addopts, and ``-qq`` suppresses the summary line this parser reads
    # (observed on the demo project, which died with "0 passed" while its
    # suite was actually green).
    argv = [
        venv.python,
        "-m",
        "pytest",
        "--tb=short",
        *config_isolation_args(repo_root, Path(venv.directory)),
    ]
    if extra_args:
        argv.extend(extra_args)
    completed = _run(argv, cwd=repo_root, timeout_s=timeout_s)
    output = (completed.stdout + ("\n" + completed.stderr if completed.stderr else "")).strip()
    lines = output.splitlines()
    result = parse_pytest_summary(completed.stdout, exit_code=completed.returncode)
    result.output_tail = lines[-30:] if len(lines) > 30 else lines
    return result


_SUMMARY_RE = re.compile(
    r"(?P<count>\d+)\s+(?P<kind>passed|failed|error|errors|skipped|xfailed|xpassed)"
)
_DURATION_RE = re.compile(r"in\s+(?P<dur>\d+(?:\.\d+)?)s\s*$")


def parse_pytest_summary(output: str, *, exit_code: int) -> PytestResult:
    """Parse pytest's human summary line into a PytestResult.

    Works with ``pytest -q`` (``N passed``) and full mode
    (``N passed, M failed``, ``N errors``). Lines that do not match are
    ignored; a missing summary is not fabricated as a pass.
    """
    passed = failed = errors = skipped = xfailed = xpassed = 0
    duration = 0.0
    for line in reversed(output.splitlines()):
        matched = _SUMMARY_RE.findall(line)
        if not matched:
            continue
        for count_text, kind in matched:
            count = int(count_text)
            if kind == "passed":
                passed += count
            elif kind == "failed":
                failed += count
            elif kind in {"error", "errors"}:
                errors += count
            elif kind == "skipped":
                skipped += count
            elif kind == "xfailed":
                xfailed += count
            elif kind == "xpassed":
                xpassed += count
        if (m := _DURATION_RE.search(line)) is not None:
            duration = float(m.group("dur"))
        break  # find the *closest to the end* summary line, then stop

    return PytestResult(
        exit_code=exit_code,
        passed=passed,
        failed=failed,
        errors=errors,
        skipped=skipped,
        xfailed=xfailed,
        xpassed=xpassed,
        duration_s=duration,
    )
