#!/usr/bin/env python
"""Run the self-written demo case, including its external held-out contract.

The demo case is ``demo/invoicekit``: an original MIT project pinned to
pydantic 1.10.22 that breaks when bumped to 2.12.4. It is **not** a benchmark
case (it is absent from ``bench/cases.json``); it exists so the pipeline can be
exercised end to end on a checkout we own.

What this script proves, in order, from real runs:

1. the project's own suite is GREEN on the old pin;
2. the external held-out contract (``demo/heldout``, never copied into the
   agent's work tree) also passes on the old pin;
3. the bump makes the suite fail (real pytest output is saved);
4. the held-out contract fails on the bumped-but-unrepaired code;
5. for each strategy (bump-only, single-shot, agent) the final state is
   recorded, then the held-out contract is copied into a scratch directory
   *outside* the checkout and run against the final tree.

Usage (from the repository root):

    python bench/demo_case.py --check
    python bench/demo_case.py --strategies bump-only,single-shot,agent
    python bench/demo_case.py --table-only

Artifacts: ``artifacts/demo/<case>/`` (raw verify JSONs, ledgers, held-out
runs, one ``result.json`` per strategy, and ``results.md``). Disposable
checkouts live under ``bench/workdirs/demo/`` and are never committed.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from upgradepilot.agent import (
    UpgradeRequest,
    _build_tiers_for,
    _run_patch,
    list_source_files,
    provider_label,
    run_upgrade,
)
from upgradepilot.config import ConfigError, load_settings_for_run
from upgradepilot.editing import EditError, apply_edits
from upgradepilot.guard import compare_snapshots, snapshot_tests
from upgradepilot.harness import resolved_versions
from upgradepilot.prepare import PreparationError, PreparedTarget, install_bump, prepare_target
from upgradepilot.run_ledger import utc_now
from upgradepilot.verify import VerifyOutcome, VerifyStatus, save_outcome, verify

REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO_SOURCE = REPO_ROOT / "demo" / "invoicekit"
DEMO_HELDOUT = REPO_ROOT / "demo" / "heldout"
CASE_ID = "demo-invoicekit-pydantic1-to-2"
PACKAGE = "pydantic"
OLD_PIN = "1.10.22"
NEW_PIN = "2.12.4"

WORKDIR_ROOT = REPO_ROOT / "bench" / "workdirs" / "demo"
ART_ROOT = REPO_ROOT / "artifacts" / "demo" / CASE_ID
STRATEGIES = ("bump-only", "single-shot", "agent")


class HeldOutResult(BaseModel):
    """One run of the external contract against a checkout state."""

    label: str
    status: str
    exit_code: int
    passed: int = 0
    failed: int = 0
    errors: int = 0
    output_tail: list[str] = Field(default_factory=list)
    command: str = ""


class StrategyResult(BaseModel):
    """One strategy applied to the demo case, from a real run."""

    case_id: str = CASE_ID
    strategy: str
    status: str
    status_note: str = ""
    agent_status: str = ""
    suite: str = ""
    exit_code: int = -1
    passed: int = 0
    failed: int = 0
    errors: int = 0
    iterations: int = 0
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float | None = None
    fully_priced: bool = False
    wall_time_s: float = 0.0
    recorded_at: str = ""
    provider: str = ""
    run_class: str = "dev"
    models: dict[str, str] = Field(default_factory=dict)
    versions: dict[str, str] = Field(default_factory=dict)
    old_pin: str = f"{PACKAGE}=={OLD_PIN}"
    new_pin: str = f"{PACKAGE}=={NEW_PIN}"
    old_pin_status: str = ""
    bumped_status: str = ""
    reference_status: str = ""
    guard_clean: bool = True
    guard_summary: str = ""
    edits: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    heldout_old_pin: HeldOutResult | None = None
    heldout_after: HeldOutResult | None = None
    artifacts: list[str] = Field(default_factory=list)


def _rel(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def _save(outcome: VerifyOutcome, dest: Path) -> str:
    return _rel(save_outcome(outcome, dest))


def _run_heldout(
    prepared: PreparedTarget,
    label: str,
    timeout_s: float,
    *,
    art_dir: Path,
) -> HeldOutResult:
    """Run the external contract from a copy outside the checkout.

    The copy lives under the run directory (never inside ``repo/``), so even a
    patched checkout cannot read or edit it during the run.
    """
    cert_dir = prepared.run_dir / f"heldout_{label}"
    if cert_dir.exists():
        shutil.rmtree(cert_dir)
    shutil.copytree(DEMO_HELDOUT, cert_dir)
    outcome = verify(
        prepared.repo,
        prepared.venv,
        timeout_s,
        ledger=prepared.ledger,
        label=f"heldout/{label}",
        extra_args=[str(cert_dir)],
    )
    art_dir.mkdir(parents=True, exist_ok=True)
    path = save_outcome(outcome, art_dir / "heldout")
    result = HeldOutResult(
        label=label,
        status=outcome.status.value,
        exit_code=outcome.result.exit_code,
        passed=outcome.result.passed,
        failed=outcome.result.failed,
        errors=outcome.result.errors,
        output_tail=outcome.result.output_tail,
        command=f"pytest {cert_dir}  (cwd={prepared.repo.root})",
    )
    (art_dir / "heldout" / f"{label}.json").write_text(
        result.model_dump_json(indent=2), encoding="utf-8"
    )
    del path
    return result


def _prepare(run_id: str) -> PreparedTarget:
    if not DEMO_SOURCE.is_dir():
        raise SystemExit(f"demo source missing: {DEMO_SOURCE}")
    target = WORKDIR_ROOT / run_id
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    return prepare_target(
        DEMO_SOURCE,
        WORKDIR_ROOT,
        PACKAGE,
        OLD_PIN,
        run_id=run_id,
        timeout_s=900.0,
    )


def run_check(timeout_s: float) -> int:
    """Prove the demo case's two preconditions and save the raw evidence."""
    art_dir = ART_ROOT / "preconditions"
    art_dir.mkdir(parents=True, exist_ok=True)
    prepared = _prepare("check")

    old_pin = verify(
        prepared.repo, prepared.venv, timeout_s, ledger=prepared.ledger, label="old-pin"
    )
    old_saved = _save(old_pin, art_dir)
    heldout_old = _run_heldout(prepared, "old-pin", timeout_s, art_dir=art_dir)

    prepared = install_bump(prepared, PACKAGE, NEW_PIN)
    versions = resolved_versions(prepared.venv, PACKAGE)
    bumped = verify(
        prepared.repo, prepared.venv, timeout_s, ledger=prepared.ledger, label="bumped"
    )
    bumped_saved = _save(bumped, art_dir)
    heldout_broken = _run_heldout(prepared, "bumped", timeout_s, art_dir=art_dir)

    payload = {
        "case_id": CASE_ID,
        "source": _rel(DEMO_SOURCE),
        "heldout_contract": _rel(DEMO_HELDOUT),
        "provider": "none (no model is called in this check)",
        "old_pin": f"{PACKAGE}=={OLD_PIN}",
        "new_pin": f"{PACKAGE}=={NEW_PIN}",
        "versions": versions,
        "old_pin_suite": old_pin.model_dump(mode="json"),
        "bumped_suite": bumped.model_dump(mode="json"),
        "heldout_on_old_pin": heldout_old.model_dump(mode="json"),
        "heldout_on_broken_code": heldout_broken.model_dump(mode="json"),
        "artifacts": [old_saved, bumped_saved],
        "recorded_at": utc_now(),
    }
    (art_dir / "preconditions.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    ok = (
        old_pin.status is VerifyStatus.GREEN
        and heldout_old.status == VerifyStatus.GREEN.value
        and bumped.status is not VerifyStatus.GREEN
        and heldout_broken.status != VerifyStatus.GREEN.value
    )
    print(
        f"old pin {PACKAGE}=={OLD_PIN}: {old_pin.status.value} "
        f"({old_pin.result.passed} passed, {old_pin.result.failed} failed)"
    )
    print(
        f"held-out contract on old pin: {heldout_old.status} "
        f"({heldout_old.passed} passed, {heldout_old.failed} failed)"
    )
    print(
        f"after bump to {NEW_PIN}: {bumped.status.value} "
        f"(exit {bumped.result.exit_code}, {bumped.result.passed} passed)"
    )
    print(
        f"held-out contract on broken code: {heldout_broken.status} "
        f"(exit {heldout_broken.exit_code})"
    )
    for line in heldout_broken.output_tail[-4:]:
        print(f"    {line}")
    print(f"preconditions {'PASS' if ok else 'FAIL'} -> {_rel(art_dir / 'preconditions.json')}")
    return 0 if ok else 1


def _certify(
    prepared: PreparedTarget,
    result: StrategyResult,
    art_dir: Path,
    timeout_s: float,
    *,
    agent_status: VerifyStatus | None,
) -> None:
    """Fold the external held-out contract into the recorded status."""
    heldout = _run_heldout(prepared, "after", timeout_s, art_dir=art_dir)
    result.heldout_after = heldout
    if agent_status is not None and agent_status is VerifyStatus.GREEN:
        if heldout.status != VerifyStatus.GREEN.value:
            result.status = VerifyStatus.OVERFIT.value
            result.status_note = (
                "visible suite GREEN but the external held-out contract failed: "
                "the patch did not preserve behaviour it could not see"
            )
        else:
            result.status = VerifyStatus.GREEN.value
            result.status_note = "visible suite and external held-out contract both GREEN"
    elif agent_status is not None:
        result.status = agent_status.value
        result.status_note = f"agent verdict {agent_status.value}; no held-out credit claimed"


def run_strategy(strategy: str, settings: Any, timeout_s: float) -> StrategyResult:
    started = time.monotonic()
    art_dir = ART_ROOT / strategy
    art_dir.mkdir(parents=True, exist_ok=True)
    result = StrategyResult(
        strategy=strategy,
        status=VerifyStatus.STUCK.value,
        recorded_at=utc_now(),
        provider=settings.llm_provider,
        run_class="submission" if settings.llm_provider == "tokenfactory" else "dev",
    )
    try:
        result.models = {role: tier.model_id for role, tier in _build_tiers_for(settings).items()}
    except Exception as exc:
        result.notes.append(f"tier mapping unavailable: {type(exc).__name__}: {exc}")

    prepared = _prepare(strategy)
    result.versions = dict(prepared.versions)

    reference = verify(
        prepared.repo,
        prepared.venv,
        timeout_s,
        ledger=prepared.ledger,
        label=f"{strategy}/old-pin",
    )
    result.artifacts.append(_save(reference, art_dir))
    result.old_pin_status = reference.status.value
    result.reference_status = reference.status.value
    result.heldout_old_pin = _run_heldout(prepared, "old-pin", timeout_s, art_dir=art_dir)

    masking_reference = reference.result if reference.status is VerifyStatus.GREEN else None
    masking_label = (
        f"old-pin GREEN run {reference.run_id}" if masking_reference else "post-bump baseline"
    )

    baseline_guard = snapshot_tests(prepared.repo.root)
    prepared = install_bump(prepared, PACKAGE, NEW_PIN)
    result.versions = resolved_versions(prepared.venv, PACKAGE)

    request = UpgradeRequest(repo=str(DEMO_SOURCE), package=PACKAGE, to_version=NEW_PIN)
    boosted = verify(
        prepared.repo, prepared.venv, timeout_s, ledger=prepared.ledger, label=f"{strategy}/bump"
    )
    result.artifacts.append(_save(boosted, art_dir))
    result.bumped_status = boosted.status.value
    result.notes.append(f"post-bump suite before repair: {boosted.status.value}")

    agent_status: VerifyStatus | None = None
    final = boosted

    if strategy == "single-shot":
        from upgradepilot.llm import LLMClient

        llm = LLMClient(settings)
        try:
            tiers = _build_tiers_for(settings)
            tier = tiers.get("default") or next(iter(tiers.values()))
            payload = _run_patch(
                llm,
                tier,
                prepared.repo.root,
                request,
                list_source_files(prepared.repo.root),
                boosted.result.output_tail,
                "Single-shot baseline: no research provider was queried.",
                1,
            )
            applied = apply_edits(prepared.repo.root, payload.files)
            result.edits = [edit.path for edit in applied]
            result.notes.append(f"one patch attempt wrote {len(applied)} file(s)")
        except EditError as exc:
            result.notes.append(f"single-shot produced no usable patch: {exc}")
        finally:
            cost = llm.cost
            result.llm_calls = cost.calls
            result.prompt_tokens = cost.total_prompt_tokens
            result.completion_tokens = cost.total_completion_tokens
            result.fully_priced = cost.fully_priced
            result.cost_usd = cost.total_cost_usd if cost.fully_priced else None
            llm.close()
        final = verify(
            prepared.repo,
            prepared.venv,
            timeout_s,
            ledger=prepared.ledger,
            label=f"{strategy}/after-patch",
        )
        result.artifacts.append(_save(final, art_dir))
    elif strategy == "agent":
        run_dir = art_dir / f"{CASE_ID}--agent"
        run_dir.mkdir(parents=True, exist_ok=True)
        report = run_upgrade(
            request=request,
            repo=prepared.repo,
            venv=prepared.venv,
            settings=settings,
            artifacts_dir=art_dir,
            run_id=f"{CASE_ID}--agent",
            ledger=prepared.ledger,
            reference_outcome=reference,
            versions=result.versions,
            run_class=result.run_class,
        )
        agent_status = report.status
        result.agent_status = report.status.value
        result.iterations = report.iterations_used
        result.llm_calls = report.cost.calls
        result.prompt_tokens = report.cost.total_prompt_tokens
        result.completion_tokens = report.cost.total_completion_tokens
        result.fully_priced = report.cost.fully_priced
        result.cost_usd = report.cost.total_cost_usd if report.cost.fully_priced else None
        result.guard_clean = report.guard_clean
        result.guard_summary = report.guard_summary
        result.edits = [edit.path for edit in report.applied_edits]
        result.notes.extend(
            f"{step.step}: {step.detail}" for step in report.steps if step.status != "ok"
        )
        measured = report.visible_outcome or report.heldout_outcome or boosted
        final = measured
        result.artifacts.append(_rel(run_dir))
        ledger_copy = art_dir / "events.jsonl"
        shutil.copyfile(prepared.ledger.path, ledger_copy)
        result.artifacts.append(_rel(ledger_copy))
        result.suite = (
            f"{measured.result.passed}P/{measured.result.failed}F/"
            f"{measured.result.errors}E (exit {measured.result.exit_code})"
        )
        result.exit_code = measured.result.exit_code
        result.passed = measured.result.passed
        result.failed = measured.result.failed
        result.errors = measured.result.errors
        _certify(prepared, result, art_dir, timeout_s, agent_status=agent_status)
        result.wall_time_s = round(time.monotonic() - started, 2)
        return result

    guard = compare_snapshots(
        baseline_guard,
        prepared.repo.root,
        package_name=PACKAGE,
        baseline_result=boosted.result,
        current_result=final.result,
        masking_reference=masking_reference,
        masking_reference_label=masking_label,
    )
    result.guard_clean = guard.clean
    result.guard_summary = guard.summary
    result.exit_code = final.result.exit_code
    result.passed = final.result.passed
    result.failed = final.result.failed
    result.errors = final.result.errors
    result.suite = (
        f"{final.result.passed}P/{final.result.failed}F/{final.result.errors}E "
        f"(exit {final.result.exit_code})"
    )
    result.status = final.status.value if guard.clean else VerifyStatus.CHEATED.value
    result.status_note = f"{strategy} final suite verdict" if guard.clean else guard.summary
    _certify(prepared, result, art_dir, timeout_s, agent_status=None)
    ledger_copy = art_dir / "events.jsonl"
    if prepared.ledger.path.is_file():
        shutil.copyfile(prepared.ledger.path, ledger_copy)
        result.artifacts.append(_rel(ledger_copy))
    result.wall_time_s = round(time.monotonic() - started, 2)
    return result


def _write(result: StrategyResult) -> Path:
    path = ART_ROOT / result.strategy / "result.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return path


def _load_results() -> list[StrategyResult]:
    rows: list[StrategyResult] = []
    if not ART_ROOT.is_dir():
        return rows
    for path in sorted(ART_ROOT.glob("*/result.json")):
        try:
            rows.append(
                StrategyResult.model_validate(json.loads(path.read_text(encoding="utf-8")))
            )
        except (OSError, ValueError):
            continue
    return rows


def build_markdown(rows: list[StrategyResult]) -> str:
    lines = [
        "# Demo case: invoicekit, pydantic 1.10.22 -> 2.12.4",
        "",
        "Self-written demo target (`demo/invoicekit`), not a benchmark case. "
        "Generated only from `artifacts/demo/<case>/<strategy>/result.json`.",
        "",
        "| Strategy | Provider | Status | Visible suite | Held-out contract | LLM calls | Wall |",
        "|----------|----------|--------|---------------|-------------------|-----------|------|",
    ]
    if not rows:
        lines.append("| *no runs recorded* | — | — | — | — | — | — |")
    for row in sorted(
        rows, key=lambda r: STRATEGIES.index(r.strategy) if r.strategy in STRATEGIES else 99
    ):
        provider = provider_label(row.provider, row.run_class) if row.provider else "not recorded"
        heldout = (
            f"{row.heldout_after.status} ({row.heldout_after.passed}P/{row.heldout_after.failed}F)"
            if row.heldout_after
            else "not run"
        )
        lines.append(
            f"| {row.strategy} | {provider} | {row.status} | {row.suite or '—'} | "
            f"{heldout} | {row.llm_calls} | {row.wall_time_s:.1f}s |"
        )
    lines.append("")
    if rows:
        env = rows[0].versions
        if env:
            lines.append(
                "Environment (read from the case venv): "
                + ", ".join(f"{key} {value}" for key, value in sorted(env.items()))
            )
            lines.append("")
    lines.append(
        "`held-out contract` is `demo/heldout/test_heldout_contract.py`, copied into a "
        "scratch directory outside the checkout and run against the final tree. The agent "
        "never sees it."
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="run and record the preconditions")
    parser.add_argument(
        "--strategies",
        default=",".join(STRATEGIES),
        help=f"comma-separated subset of: {', '.join(STRATEGIES)}",
    )
    parser.add_argument(
        "--table-only", action="store_true", help="regenerate results.md from result JSONs"
    )
    args = parser.parse_args(argv)

    if args.table_only:
        ART_ROOT.mkdir(parents=True, exist_ok=True)
        (ART_ROOT / "results.md").write_text(build_markdown(_load_results()), encoding="utf-8")
        print(f"wrote {_rel(ART_ROOT / 'results.md')}")
        return 0

    if args.check:
        return run_check(300.0)

    selected = [s.strip() for s in args.strategies.split(",") if s.strip()]
    unknown = [s for s in selected if s not in STRATEGIES]
    if unknown:
        parser.error(f"unknown strategy/strategies: {', '.join(unknown)}")

    try:
        settings = load_settings_for_run()
    except ConfigError as exc:
        print(f"configuration error: {exc}")
        return 1
    timeout_s = float(settings.pytest_timeout_seconds)

    exit_code = 0
    for strategy in selected:
        print(f"[{strategy}] running ...", flush=True)
        try:
            result = run_strategy(strategy, settings, timeout_s)
        except (PreparationError, OSError) as exc:
            print(f"[{strategy}] SETUP FAILED: {type(exc).__name__}: {exc}")
            exit_code = 1
            continue
        path = _write(result)
        print(
            f"[{strategy}] {result.status} ({result.suite or result.agent_status}, "
            f"{result.llm_calls} call(s), {result.wall_time_s:.1f}s) -> {_rel(path)}"
        )
        if result.status_note:
            print(f"    note: {result.status_note}")
        for note in result.notes:
            print(f"    {note}")

    ART_ROOT.mkdir(parents=True, exist_ok=True)
    (ART_ROOT / "results.md").write_text(build_markdown(_load_results()), encoding="utf-8")
    print(f"wrote {_rel(ART_ROOT / 'results.md')}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
