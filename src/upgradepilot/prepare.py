"""Prepare a disposable target checkout and install one requested upgrade.

The CLI never patches the user's original checkout. It copies the source tree
into ``<artifacts>/<run-id>/repo`` (excluding VCS/venv/cache metadata), creates
a clean venv there, installs the project's own dependencies, installs the old
pin (when the caller knows it), and finally installs
``<package>==<to_version>``. The resulting ``RepoWorkdir`` and ``VenvInfo``
are the only mutable target the agent sees.

Install order matters for evidence: the old pin goes in before the bump so the
environment that broke is the environment we recorded, and every stage's
resolved versions (Python, pytest, the upgraded package) are read back from
the venv with ``importlib.metadata`` and written to ``setup.json``.

This module deliberately has no LLM logic. It is the setup boundary: if it
fails, the failure is recorded in ``setup.json`` and no agent run is claimed.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field, replace
from pathlib import Path

from upgradepilot.guard import SKIP_DIRS
from upgradepilot.harness import (
    HarnessError,
    RepoWorkdir,
    VenvInfo,
    make_pinned_venv,
    pip_install,
    resolved_versions,
)
from upgradepilot.run_ledger import RunLedger, new_run_id
from upgradepilot.verify import VerifyOutcome, verify

_COPY_SKIP = frozenset(SKIP_DIRS | {"artifacts", ".coverage", "htmlcov"})
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
# Harness tooling, not project runtime dependencies. ``pytest-mock`` is the
# only common pytest plugin the verified benchmark repos import directly; if
# it is absent, collection fails before the agent can see a real breakage.
_TEST_TOOLS = ("pytest", "pytest-mock")


class PreparationError(RuntimeError):
    """The disposable checkout or dependency installation could not be built."""


@dataclass(frozen=True)
class PreparedTarget:
    """Everything the agent needs to run against a disposable target."""

    run_id: str
    run_dir: Path
    repo: RepoWorkdir
    venv: VenvInfo
    ledger: RunLedger
    setup_path: Path
    versions: dict[str, str] = field(default_factory=dict)
    version_stages: dict[str, dict[str, str]] = field(default_factory=dict)
    reference_outcome: VerifyOutcome | None = None


def _copy_ignore(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name in _COPY_SKIP or name.endswith(".egg-info")}


def _git_text(source: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(source), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def _git_snapshot(source: Path) -> tuple[str, bool]:
    commit = _git_text(source, "rev-parse", "HEAD")
    if commit is None:
        return "", False
    status = _git_text(source, "status", "--porcelain")
    return commit, bool(status)


def _write_setup(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _update_setup_versions(
    path: Path, stage: str, versions: dict[str, str]
) -> dict[str, dict[str, str]]:
    """Merge one install stage's versions into ``setup.json``; return all stages."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = {}
    stages = payload.get("versions")
    if not isinstance(stages, dict):
        stages = {}
    stages[stage] = versions
    payload["versions"] = stages
    _write_setup(path, payload)
    return stages


def prepare_target(
    source: Path,
    artifacts_root: Path,
    package: str,
    to_version: str,
    *,
    from_version: str | None = None,
    run_id: str | None = None,
    timeout_s: float = 900.0,
    verify_old_pin: bool = False,
    pytest_timeout_s: float = 300.0,
) -> PreparedTarget:
    """Copy ``source`` and install ``package==to_version`` in a clean venv.

    When ``from_version`` is given it is installed *before* ``to_version``, so
    the bump lands on top of the old pin instead of on a fresh resolution.
    ``verify_old_pin`` runs the suite while the old pin is still installed and
    records it as the masking reference for the agent's guard.

    The copy excludes VCS/venv/cache directories and the local ``artifacts``
    directory so a run can never recurse into its own evidence. The original
    source tree is never modified.
    """
    source = source.resolve()
    if not source.is_dir():
        raise PreparationError(f"target source is not a directory: {source}")
    if not package.strip() or not to_version.strip():
        raise PreparationError("package and to_version must both be non-empty")

    run_id = run_id or new_run_id()
    if not _SAFE_RUN_ID.fullmatch(run_id) or ".." in run_id:
        raise PreparationError(f"unsafe run id: {run_id!r}")

    artifacts_root = artifacts_root.resolve()
    artifacts_root.mkdir(parents=True, exist_ok=True)
    run_dir = artifacts_root / run_id
    if run_dir.exists():
        raise PreparationError(f"run directory already exists: {run_dir}")
    run_dir.mkdir(parents=True)

    repo_dir = run_dir / "repo"
    try:
        shutil.copytree(source, repo_dir, ignore=_copy_ignore, symlinks=True)
    except OSError as exc:
        raise PreparationError(f"could not copy target checkout: {exc}") from exc

    commit, dirty = _git_snapshot(source)
    ledger = RunLedger(run_dir)
    setup_path = run_dir / "setup.json"
    setup: dict[str, object] = {
        "status": "starting",
        "run_id": run_id,
        "source": str(source),
        "repo": str(repo_dir),
        "commit": commit,
        "dirty": dirty,
        "package": package,
        "from_version": from_version,
        "to_version": to_version,
        "commands": [],
        "versions": {},
        "error": None,
    }
    _write_setup(setup_path, setup)
    ledger.append(
        "setup",
        run_id=run_id,
        source=str(source),
        repo=str(repo_dir),
        commit=commit,
        dirty=dirty,
        package=package,
        from_version=from_version,
        to_version=to_version,
    )

    commands: list[list[str]] = []
    stages: dict[str, dict[str, str]] = {}
    try:
        venv = make_pinned_venv(repo_dir)

        def install(*args: str) -> None:
            command = [venv.python, "-m", "pip", "install", "--quiet", *args]
            commands.append(command)
            setup["commands"] = commands
            _write_setup(setup_path, setup)
            output = pip_install(venv, *args, timeout_s=timeout_s)
            ledger.append(
                "install",
                command=args,
                output_tail=output[-400:],
            )

        if (repo_dir / "pyproject.toml").is_file() or (repo_dir / "setup.py").is_file():
            install("-e", ".")
        if (repo_dir / "requirements.txt").is_file():
            install("-r", "requirements.txt")
        for tool in _TEST_TOOLS:
            install(tool)
        stages["after_project_install"] = resolved_versions(venv, package)
        if from_version is None and verify_old_pin:
            # The caller did not name an old pin, but the project's own
            # metadata pinned one: record and re-install exactly that version
            # so the reference run is on the pin the project asked for.
            resolved_old = stages["after_project_install"].get(package, "")
            if resolved_old and resolved_old != "not-installed":
                from_version = resolved_old
                setup["from_version"] = resolved_old
                _write_setup(setup_path, setup)
        if from_version:
            install(f"{package}=={from_version}")
            stages["after_old_pin"] = resolved_versions(venv, package)
        if verify_old_pin:
            reference_outcome = verify(
                RepoWorkdir(root=repo_dir, source=str(source), commit=commit or "unknown"),
                venv,
                timeout_s=pytest_timeout_s,
                ledger=ledger,
                label="setup/old-pin",
            )
            reference_path = run_dir / f"old_pin_{reference_outcome.status.value.lower()}.json"
            reference_path.write_text(
                reference_outcome.model_dump_json(indent=2), encoding="utf-8"
            )
            setup["old_pin_reference"] = {
                "path": str(reference_path),
                "status": reference_outcome.status.value,
                "passed": reference_outcome.result.passed,
                "failed": reference_outcome.result.failed,
                "skipped": reference_outcome.result.skipped,
                "xfailed": reference_outcome.result.xfailed,
            }
            _write_setup(setup_path, setup)
            ledger.append(
                "old_pin_reference",
                status=reference_outcome.status.value,
                path=str(reference_path),
            )
        else:
            reference_outcome = None
        install(f"{package}=={to_version}")
        stages["after_bump"] = resolved_versions(venv, package)
        setup["versions"] = stages
    except (HarnessError, OSError) as exc:
        setup["status"] = "failed"
        setup["error"] = f"{type(exc).__name__}: {exc}"
        setup["commands"] = commands
        setup["versions"] = stages
        _write_setup(setup_path, setup)
        ledger.append("setup_failed", error=setup["error"], setup=str(setup_path))
        raise PreparationError(
            f"target setup failed; see {setup_path}: {type(exc).__name__}: {exc}"
        ) from exc

    setup["status"] = "ok"
    setup["commands"] = commands
    setup["versions"] = stages
    _write_setup(setup_path, setup)
    ledger.append(
        "setup_ok",
        setup=str(setup_path),
        commands=len(commands),
        versions=stages.get("after_bump", {}),
    )

    return PreparedTarget(
        run_id=run_id,
        run_dir=run_dir,
        repo=RepoWorkdir(root=repo_dir, source=str(source), commit=commit or "unknown"),
        venv=venv,
        ledger=ledger,
        setup_path=setup_path,
        versions=stages.get("after_bump", {}),
        version_stages=stages,
        reference_outcome=reference_outcome,
    )


def install_bump(
    prepared: PreparedTarget,
    package: str,
    to_version: str,
    *,
    timeout_s: float = 900.0,
) -> PreparedTarget:
    """Install ``package==to_version`` over the prepared environment.

    This is the second half of the two-phase flow used when a caller needs an
    old-pin run first (the masking reference): prepare at the old pin, verify
    it GREEN, then call this, then verify the bump. Resolved versions are
    recorded in ``setup.json`` exactly like the one-shot path.
    """
    output = pip_install(prepared.venv, f"{package}=={to_version}", timeout_s=timeout_s)
    versions = resolved_versions(prepared.venv, package)
    stages = _update_setup_versions(prepared.setup_path, "after_bump", versions)
    prepared.ledger.append(
        "install",
        command=(f"{package}=={to_version}",),
        output_tail=output[-400:],
        stage="bump",
    )
    return replace(prepared, versions=versions, version_stages=stages)
