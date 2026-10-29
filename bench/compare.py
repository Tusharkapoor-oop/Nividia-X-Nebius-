#!/usr/bin/env python
"""Run one benchmark case under several repair strategies and record outcomes.

Phase 5 compares UpgradePilot's full loop against weaker strategies on the same
pinned checkout, so the results table can show what the agent actually buys:

  bump-only    no repair at all -- the control: the suite as the bump leaves it
  codemod      deterministic, mechanical renames for bumps with a documented
               rename table (Pydantic v1 -> v2); no model is called
  single-shot  exactly one model patch attempt: no triage, no research, no
               iteration, applied and verified once
  agent        the full Phase 4 loop (triage, research, iterate, certify)

Usage (from the repo root):
    python bench/compare.py --list
    python bench/compare.py --case pydantic-argparse-pydantic1-to-2
    python bench/compare.py --case <id> --strategies bump-only,codemod
    python bench/compare.py --table-only

Each row is written to ``artifacts/phase5/<case>/<strategy>.json`` from a real
run, with its pytest outcomes and ledger copied next to it. ``--table-only``
renders the markdown table from those JSONs alone. Disposable checkouts and
venvs live under ``bench/workdirs/phase5/`` and are never committed.
"""

from __future__ import annotations

import argparse
import json
import re
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
from upgradepilot.guard import compare_snapshots, guarded_status, snapshot_tests
from upgradepilot.harness import HarnessError, clone_pinned, pip_install, resolved_versions
from upgradepilot.llm import LLMClient
from upgradepilot.prepare import PreparationError, install_bump, prepare_target
from upgradepilot.run_ledger import utc_now
from upgradepilot.verify import VerifyOutcome, VerifyStatus, save_outcome, verify

REPO_ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = REPO_ROOT / "bench" / "cases.json"
WORKDIR_ROOT = REPO_ROOT / "bench" / "workdirs" / "cases"
PHASE5_WORKDIR_ROOT = REPO_ROOT / "bench" / "workdirs" / "phase5"
ART_ROOT = REPO_ROOT / "artifacts" / "phase5"

STRATEGIES = ("bump-only", "codemod", "single-shot", "agent")

# Mechanical renames only. Documented in Pydantic's v1 -> v2 migration guide;
# ambiguous names (``.dict()``, ``.json()``, ``.copy()``) are deliberately NOT
# rewritten, because a plain dict also has them and rewriting those would break
# code that the bump never touched.
_PYDANTIC_V1_TO_V2: tuple[tuple[str, str, str], ...] = (
    (r"@validator\(", "@field_validator(", "validator -> field_validator"),
    (r"@root_validator\(", "@model_validator(", "root_validator -> model_validator"),
    (
        r"\bfrom pydantic import validator\b",
        "from pydantic import field_validator",
        "import validator -> field_validator",
    ),
    (
        r"\bfrom pydantic import root_validator\b",
        "from pydantic import model_validator",
        "import root_validator -> model_validator",
    ),
    (r"\.parse_obj\(", ".model_validate(", "parse_obj -> model_validate"),
    (r"\.parse_raw\(", ".model_validate_json(", "parse_raw -> model_validate_json"),
    (r"\.construct\(", ".model_construct(", "construct -> model_construct"),
    (r"\.schema\(", ".model_json_schema(", "schema -> model_json_schema"),
    (
        r"\.update_forward_refs\(",
        ".model_rebuild(",
        "update_forward_refs -> model_rebuild",
    ),
    (r"__fields__", "model_fields", "__fields__ -> model_fields"),
    (
        r"\bfrom pydantic import BaseSettings\b",
        "from pydantic_settings import BaseSettings",
        "BaseSettings moved to pydantic_settings",
    ),
)

_CODEMOD_TABLES: dict[tuple[str, int], tuple[tuple[str, str, str], ...]] = {
    ("pydantic", 2): _PYDANTIC_V1_TO_V2,
}


class StrategyResult(BaseModel):
    """One strategy applied to one case, from a real run."""

    case_id: str
    strategy: str
    status: str
    exit_code: int = -1
    passed: int = 0
    failed: int = 0
    errors: int = 0
    suite_duration_s: float = 0.0
    wall_time_s: float = 0.0
    iterations: int = 0
    llm_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float | None = None
    fully_priced: bool = False
    guard_clean: bool = True
    guard_summary: str = "clean"
    edits: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    recorded_at: str = ""
    # Provider provenance: a result file must never be mistakable for a
    # Token Factory run when it was produced on the dev provider.
    provider: str = ""
    run_class: str = "dev"
    models: dict[str, str] = Field(default_factory=dict)
    versions: dict[str, str] = Field(default_factory=dict)
    reference_status: str = ""
    reference_skipped: int = 0
    reference_xfailed: int = 0


def _load_cases() -> dict[str, dict[str, Any]]:
    data = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    return {c["id"]: c for c in data["cases"]}


def _pin_version(pin: str) -> str:
    return pin.split("==", 1)[1] if "==" in pin else pin


def _major(version: str) -> int:
    match = re.match(r"(\d+)", version.strip())
    return int(match.group(1)) if match else 0


def _codemod_rules(case: dict[str, Any]) -> tuple[tuple[str, str, str], ...]:
    """Mechanical renames for this bump, or an empty table when none exists."""
    table = _CODEMOD_TABLES.get((case["dep"], _major(case["new_pin"])))
    if table is None:
        return ()
    if _major(case["old_pin"]) == _major(case["new_pin"]):
        return ()
    return table


def _apply_codemod(root: Path, rules: tuple[tuple[str, str, str], ...]) -> list[str]:
    """Apply regex renames to non-test Python sources; return changed paths."""
    changed: list[str] = []
    for rel in list_source_files(root):
        path = root / rel
        if not path.is_file():
            continue
        original = path.read_text(encoding="utf-8", errors="replace")
        updated = original
        for pattern, replacement, _note in rules:
            updated = re.sub(pattern, replacement, updated)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            changed.append(rel)
    return changed


def _record_dir(case_id: str, strategy: str) -> Path:
    return ART_ROOT / case_id / strategy


def _copy_ledger(prepared_ledger: Path, dest: Path) -> str | None:
    if not prepared_ledger.is_file():
        return None
    target = dest / "events.jsonl"
    shutil.copyfile(prepared_ledger, target)
    return str(target.relative_to(REPO_ROOT))


def _save(outcome: VerifyOutcome, layer: str, dest: Path) -> str:
    path = save_outcome(outcome, dest / layer)
    return str(path.relative_to(REPO_ROOT))


def _prepare(case: dict[str, Any], strategy: str) -> Any:
    """Fresh disposable checkout + venv at the *old* pin.

    The bump is installed as an explicit second step (``install_bump``) so the
    old-pin suite can be recorded as the masking reference before the bump.
    """
    source = WORKDIR_ROOT / case["id"]
    if not source.is_dir():
        clone_pinned(case["source"], case["commit"], WORKDIR_ROOT, name=case["id"])
    if not source.is_dir():
        raise HarnessError(f"target checkout missing after clone: {source}")
    run_id = f"{case['id']}--{strategy}"
    target = PHASE5_WORKDIR_ROOT / run_id
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    return prepare_target(
        source,
        PHASE5_WORKDIR_ROOT,
        case["dep"],
        _pin_version(case["old_pin"]),
        run_id=run_id,
        timeout_s=900.0,
    )


def _run_strategy(
    case: dict[str, Any],
    strategy: str,
    settings: Any,
    timeout_s: float,
) -> StrategyResult:
    started = time.monotonic()
    art_dir = _record_dir(case["id"], strategy)
    art_dir.mkdir(parents=True, exist_ok=True)
    result = StrategyResult(
        case_id=case["id"],
        strategy=strategy,
        status=VerifyStatus.STUCK.value,
        recorded_at=utc_now(),
    )

    prepared = _prepare(case, strategy)
    result.provider = settings.llm_provider
    result.run_class = "submission" if settings.llm_provider == "tokenfactory" else "dev"
    try:
        result.models = {role: tier.model_id for role, tier in _build_tiers_for(settings).items()}
    except Exception as exc:  # tier catalog unavailable: record why, keep the run
        result.notes.append(f"tier mapping unavailable: {type(exc).__name__}: {exc}")

    # 1. Old pin: the reference run for skip/xfail masking (D1).
    reference = verify(
        prepared.repo,
        prepared.venv,
        timeout_s,
        ledger=prepared.ledger,
        label=f"{strategy}/old-pin",
    )
    result.artifacts.append(_save(reference, "old-pin", art_dir))
    result.reference_status = reference.status.value
    result.reference_skipped = reference.result.skipped
    result.reference_xfailed = reference.result.xfailed
    result.notes.append(
        f"old-pin suite: {reference.status.value} "
        f"({reference.result.passed} passed, {reference.result.failed} failed, "
        f"{reference.result.skipped} skipped, {reference.result.xfailed} xfailed)"
    )
    masking_reference = reference.result if reference.status is VerifyStatus.GREEN else None
    masking_label = (
        f"old-pin run {reference.run_id}" if masking_reference else "post-bump baseline"
    )

    # 2. The bump, installed on top of the old pin.
    prepared = install_bump(prepared, case["dep"], _pin_version(case["new_pin"]))
    result.versions = resolved_versions(prepared.venv, case["dep"])
    for pin in case.get("pre_install_pins", []):
        pip_install(prepared.venv, pin, timeout_s=900.0)
        result.notes.append(f"pre-install pin: {pin}")

    baseline_guard = snapshot_tests(prepared.repo.root)
    request = UpgradeRequest(
        repo=str(WORKDIR_ROOT / case["id"]),
        package=case["dep"],
        to_version=case["new_pin"],
    )

    bumped = verify(
        prepared.repo,
        prepared.venv,
        timeout_s,
        ledger=prepared.ledger,
        label=f"{strategy}/bump-only",
    )
    result.artifacts.append(_save(bumped, "bump-only", art_dir))
    result.notes.append(f"post-bump suite before any repair: {bumped.status.value}")
    final = bumped

    if strategy == "codemod":
        rules = _codemod_rules(case)
        if not rules:
            result.notes.append(
                f"no mechanical rename table for {case['dep']} "
                f"{case['old_pin']} -> {case['new_pin']}; codemod is the control"
            )
        else:
            changed = _apply_codemod(prepared.repo.root, rules)
            result.edits = changed
            result.notes.append(
                f"applied {len(rules)} mechanical rule(s) to {len(changed)} file(s)"
            )
            result.notes.append(
                "ambiguous renames (.dict(), .json(), .copy()) are intentionally skipped"
            )
            final = verify(
                prepared.repo,
                prepared.venv,
                timeout_s,
                ledger=prepared.ledger,
                label=f"{strategy}/after-codemod",
            )
            result.artifacts.append(_save(final, "final", art_dir))
    elif strategy == "single-shot":
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
                bumped.result.output_tail,
                "Single-shot baseline: no research provider was queried.",
                1,
            )
            applied = apply_edits(prepared.repo.root, payload.files)
            result.edits = [edit.path for edit in applied]
            result.notes.append(f"one patch attempt, {len(applied)} file(s) written")
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
        result.artifacts.append(_save(final, "final", art_dir))
    elif strategy == "agent":
        agent_run_id = f"{case['id']}--{strategy}"
        run_artifacts = art_dir / agent_run_id
        run_artifacts.mkdir(parents=True, exist_ok=True)
        report = run_upgrade(
            request=request,
            repo=prepared.repo,
            venv=prepared.venv,
            settings=settings,
            artifacts_dir=art_dir,
            run_id=agent_run_id,
            ledger=prepared.ledger,
            reference_outcome=reference,
            versions=result.versions,
            run_class=result.run_class,
        )
        result.iterations = report.iterations_used
        result.llm_calls = report.cost.calls
        result.prompt_tokens = report.cost.total_prompt_tokens
        result.completion_tokens = report.cost.total_completion_tokens
        result.fully_priced = report.cost.fully_priced
        result.cost_usd = report.cost.total_cost_usd if report.cost.fully_priced else None
        result.guard_clean = report.guard_clean
        result.guard_summary = report.guard_summary
        result.edits = [edit.path for edit in report.applied_edits]
        apply_note = next(
            (step.detail for step in report.steps if step.step == "apply" and step.detail),
            "",
        )
        if apply_note:
            result.notes.append(apply_note)
        measured = report.visible_outcome or report.heldout_outcome or bumped
        result.status = report.status.value
        result.exit_code = measured.result.exit_code
        result.passed = measured.result.passed
        result.failed = measured.result.failed
        result.errors = measured.result.errors
        result.suite_duration_s = measured.result.duration_s
        result.artifacts.append(str(run_artifacts.relative_to(REPO_ROOT)))
        ledger_copy = _copy_ledger(prepared.ledger.path, art_dir)
        if ledger_copy:
            result.artifacts.append(ledger_copy)
        result.wall_time_s = round(time.monotonic() - started, 2)
        return result

    guard = compare_snapshots(
        baseline_guard,
        prepared.repo.root,
        package_name=case["dep"],
        baseline_result=bumped.result,
        current_result=final.result,
        masking_reference=masking_reference,
        masking_reference_label=masking_label,
    )
    result.status = guarded_status(final.status, guard).value
    result.exit_code = final.result.exit_code
    result.passed = final.result.passed
    result.failed = final.result.failed
    result.errors = final.result.errors
    result.suite_duration_s = final.result.duration_s
    result.guard_clean = guard.clean
    result.guard_summary = guard.summary
    ledger_copy = _copy_ledger(prepared.ledger.path, art_dir)
    if ledger_copy:
        result.artifacts.append(ledger_copy)
    result.wall_time_s = round(time.monotonic() - started, 2)
    return result


def _write(result: StrategyResult) -> Path:
    path = _record_dir(result.case_id, result.strategy) / "result.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    return path


def _load_results() -> list[StrategyResult]:
    rows: list[StrategyResult] = []
    if not ART_ROOT.is_dir():
        return rows
    for path in sorted(ART_ROOT.glob("*/*/result.json")):
        try:
            rows.append(
                StrategyResult.model_validate(json.loads(path.read_text(encoding="utf-8")))
            )
        except (OSError, ValueError):
            continue
    return rows


def build_markdown(rows: list[StrategyResult]) -> str:
    """Render the Phase 5 comparison table from recorded rows only."""
    lines = [
        "# Phase 5 strategy comparison",
        "",
        "Generated from `artifacts/phase5/<case>/<strategy>/result.json`. Every "
        "row is one real run of one strategy on the same pinned checkout for "
        "that case; nothing here is estimated.",
        "",
        "| Case | Strategy | Provider | Status | Suite | Iterations | LLM calls | Tokens | Cost | Wall |",
        "|------|----------|----------|--------|-------|------------|-----------|--------|------|------|",
    ]
    if not rows:
        lines.append("| *no runs recorded* | — | — | — | — | — | — | — | — | — |")
    for row in sorted(rows, key=lambda r: (r.case_id, STRATEGIES.index(r.strategy))):
        suite = f"{row.passed}P/{row.failed}F/{row.errors}E (exit {row.exit_code})"
        tokens = f"{row.prompt_tokens}in/{row.completion_tokens}out"
        cost = f"${row.cost_usd:.4f}" if row.cost_usd is not None else "unpriced"
        provider = provider_label(row.provider, row.run_class) if row.provider else "not recorded"
        lines.append(
            f"| {row.case_id} | {row.strategy} | {provider} | {row.status} | {suite} | "
            f"{row.iterations} | {row.llm_calls} | {tokens} | {cost} | {row.wall_time_s:.1f}s |"
        )
    lines.append("")
    lines.append(
        "Legend: **bump-only** is the control (no repair), **codemod** is the "
        "mechanical rename table, **single-shot** is one model patch attempt, "
        "**agent** is the full Phase 4 loop. `unpriced` means the active "
        "provider publishes no price for the model, so no dollar figure is "
        "claimed."
    )
    versions = {row.case_id: row.versions for row in rows if row.versions}
    if versions:
        lines.append("")
        lines.append("Resolved environment per case (read from the venv after install):")
        lines.append("")
        for case_id in sorted(versions):
            rendered = ", ".join(f"{k} {v}" for k, v in sorted(versions[case_id].items()))
            lines.append(f"- `{case_id}`: {rendered}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="list known cases")
    parser.add_argument("--case", action="append", help="case id to compare (repeatable)")
    parser.add_argument(
        "--strategies",
        default=",".join(STRATEGIES),
        help=f"comma-separated subset of: {', '.join(STRATEGIES)}",
    )
    parser.add_argument(
        "--table-only",
        action="store_true",
        help="only regenerate artifacts/phase5/results.md from recorded runs",
    )
    args = parser.parse_args(argv)

    cases = _load_cases()
    if args.list:
        for case_id, case in cases.items():
            print(f"{case_id:28s} {case['status']:28s} {case['dep']} {case['old_pin']}")
        return 0

    if args.table_only:
        ART_ROOT.mkdir(parents=True, exist_ok=True)
        (ART_ROOT / "results.md").write_text(build_markdown(_load_results()), encoding="utf-8")
        print(f"wrote {ART_ROOT / 'results.md'}")
        return 0

    if not args.case:
        parser.error("--case or --table-only is required")
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
    for case_id in args.case:
        if case_id not in cases:
            print(f"unknown case {case_id!r}")
            exit_code = 2
            continue
        case = cases[case_id]
        for strategy in selected:
            print(f"[{case_id}] strategy={strategy} ...", flush=True)
            try:
                result = _run_strategy(case, strategy, settings, timeout_s)
            except (HarnessError, PreparationError, OSError) as exc:
                print(f"[{case_id}/{strategy}] SETUP FAILED: {type(exc).__name__}: {exc}")
                exit_code = 1
                continue
            path = _write(result)
            print(
                f"[{case_id}/{strategy}] {result.status} "
                f"({result.passed}P/{result.failed}F/{result.errors}E, "
                f"{result.llm_calls} call(s), {result.wall_time_s:.1f}s) -> {path}"
            )
            if result.notes:
                for note in result.notes:
                    print(f"    note: {note}")

    ART_ROOT.mkdir(parents=True, exist_ok=True)
    (ART_ROOT / "results.md").write_text(build_markdown(_load_results()), encoding="utf-8")
    print(f"wrote {ART_ROOT / 'results.md'}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
