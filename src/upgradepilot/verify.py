"""Verify-step: run pytest on the target repo and classify the outcome.

Status mapping (the plan's fixed vocabulary):

- ``GREEN``    : pytest exit 0 — everything that ran, passed.
- ``STUCK``    : pytest exit 1 — real test failures to fix.
- ``ENV_FAIL`` : pytest could not run meaningfully (collection error,
                 internal error, usage error, no tests, a missing dependency
                 in the tail, or a harness timeout).

``GREEN``, ``STUCK``, ``ENV_FAIL`` are classified here from pytest
behavior. ``CHEATED`` is produced by the test-suite guard
(``upgradepilot.guard``) and never by this classifier; ``OVERFIT`` is
produced by the held-out split (``upgradepilot.heldout``) when the visible
tests pass but the held-out tests fail, and never by this classifier.
Nothing weaker than ``GREEN`` certifies a run.
"""

from __future__ import annotations

import enum
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, Field

from upgradepilot.harness import HarnessError, RepoWorkdir, VenvInfo, run_pytest
from upgradepilot.models import PytestResult
from upgradepilot.run_ledger import RunLedger, new_run_id

_EXIT_COLLECTION = 2
_EXIT_INTERNAL = 3
_EXIT_USAGE = 4
_EXIT_NO_TESTS = 5


class VerifyStatus(enum.StrEnum):
    """Outcome vocabulary shared by the CLI, ledger, and proof card."""

    GREEN = "GREEN"
    STUCK = "STUCK"
    ENV_FAIL = "ENV_FAIL"
    CHEATED = "CHEATED"
    OVERFIT = "OVERFIT"


class VerifyOutcome(BaseModel):
    """One pytest invocation plus the status it justifies."""

    status: VerifyStatus
    run_id: str
    result: PytestResult
    reasons: list[str] = Field(default_factory=list)


def classify_pytest(result: PytestResult) -> VerifyStatus:
    """Pure status classifier; unit-tested, never calls subprocess."""
    if result.ok:
        return VerifyStatus.GREEN
    tail_text = "\n".join(result.output_tail)
    if "ModuleNotFoundError" in tail_text or "ImportError" in tail_text:
        return VerifyStatus.ENV_FAIL
    if result.exit_code in {
        _EXIT_COLLECTION,
        _EXIT_INTERNAL,
        _EXIT_USAGE,
        _EXIT_NO_TESTS,
    }:
        return VerifyStatus.ENV_FAIL
    if result.exit_code == 1:
        return VerifyStatus.STUCK
    return VerifyStatus.ENV_FAIL


def verify(
    repo: RepoWorkdir,
    venv: VenvInfo,
    timeout_s: float,
    *,
    ledger: RunLedger | None = None,
    label: str = "verify",
    extra_args: list[str] | None = None,
) -> VerifyOutcome:
    """Given a prepared repo and venv, run pytest once and classify it.

    ``extra_args`` restricts the run to a subset (visible or held-out test
    paths, for example); when omitted the whole suite runs.
    """
    run_id = new_run_id()
    try:
        result = run_pytest(venv, repo.root, timeout_s=timeout_s, extra_args=extra_args)
    except HarnessError as exc:
        result = PytestResult(exit_code=-1, output_tail=[str(exc)])
        status = VerifyStatus.ENV_FAIL
        reasons = [type(exc).__name__ + ": " + str(exc)]
        if ledger is not None:
            ledger.append(
                label,
                run_id=run_id,
                cwd=str(repo.root),
                status=status.value,
                result=result.model_dump(),
                reasons=reasons,
            )
        return VerifyOutcome(status=status, run_id=run_id, result=result, reasons=reasons)

    status = classify_pytest(result)
    reasons = [f"pytest exit {result.exit_code}: {status.value}"]
    if ledger is not None:
        ledger.append(
            label,
            run_id=run_id,
            cwd=str(repo.root),
            status=status.value,
            result=result.model_dump(),
            reasons=reasons,
        )
    return VerifyOutcome(status=status, run_id=run_id, result=result, reasons=reasons)


def save_outcome(outcome: VerifyOutcome, artifacts_dir: Path) -> Path:
    """Persist one outcome's JSON as evidence next to its events."""
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    path = artifacts_dir / f"{outcome.run_id}_{label_slug(outcome)}.json"
    path.write_text(outcome.model_dump_json(indent=2), encoding="utf-8")
    return path


def label_slug(outcome: VerifyOutcome) -> str:
    """Lowercase status used in evidence file names."""
    return outcome.status.value.lower()


def verify_with_rollback(
    repo: RepoWorkdir,
    venv: VenvInfo,
    timeout_s: float,
    *,
    ledger: RunLedger | None = None,
    label: str = "verify",
    extra_args: list[str] | None = None,
    previous_failures: int | None = None,
    verify_fn: Callable[..., VerifyOutcome] = verify,
) -> VerifyOutcome:
    """Run :func:`verify` inside a checkpoint/rollback wrapper.

    The working tree is snapshotted immediately before pytest runs.
    Keeps the tree in place if:
    - outcome is ``GREEN``; OR
    - failing test count strictly decreased (partial progress:
      ``outcome.result.failed < previous_failures``).

    Otherwise restores the snapshot so regressions or non-progressing edits
    do not leak into subsequent iterations.
    """
    from upgradepilot.checkpoints import RepoCheckpoint

    checkpoint = RepoCheckpoint.capture(repo.root)
    if extra_args is None:
        outcome = verify_fn(repo, venv, timeout_s, ledger=ledger, label=label)
    else:
        outcome = verify_fn(
            repo,
            venv,
            timeout_s,
            ledger=ledger,
            label=label,
            extra_args=extra_args,
        )

    if outcome.status is VerifyStatus.GREEN:
        return outcome

    # Partial progress check: keep patch if failing tests strictly decreased
    if (
        previous_failures is not None
        and outcome.status is VerifyStatus.STUCK
        and outcome.result.failed < previous_failures
    ):
        outcome.reasons.append(
            f"partial_progress: kept patch because failures decreased from "
            f"{previous_failures} to {outcome.result.failed}"
        )
        return outcome

    restored = checkpoint.restore(repo.root)
    outcome.reasons.append(f"rollback: restored {restored} files to pre-run state")
    if ledger is not None:
        ledger.append(
            "rollback", run_id=outcome.run_id, status="ROLLED_BACK", restored_files=restored
        )
    return outcome
