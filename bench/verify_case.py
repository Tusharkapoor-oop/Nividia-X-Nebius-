#!/usr/bin/env python
"""Reproduce and verify one benchmark case from bench/cases.json.

Usage (from the repo root):
    python bench/verify_case.py --list
    python bench/verify_case.py --case <case_id>

For a case with "status": "candidate", the script performs, for real:
  1. clone the repo at the pinned commit into bench/workdirs/cases/<id>/
  2. create a clean venv inside it
  3. pip install the repo's old dependency pin plus pytest
  4. run pytest  -> must be GREEN; saved to artifacts/phase2/<id>/
  5. pip install the ONE dependency at its new pin
  6. run pytest  -> saved to artifacts/phase2/<id>/

A case is promoted from "candidate" to "verified-passing-to-failing" in
bench/cases.json ONLY when step 4 is GREEN and step 6 is STUCK/ENV_FAIL
with real recorded runs. Nothing is claimed without those runs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from upgradepilot.harness import clone_pinned, make_pinned_venv, pip_install
from upgradepilot.run_ledger import RunLedger
from upgradepilot.verify import VerifyOutcome, VerifyStatus, save_outcome, verify

REPO_ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = REPO_ROOT / "bench" / "cases.json"
WORKDIR_ROOT = REPO_ROOT / "bench" / "workdirs" / "cases"
ART_ROOT = REPO_ROOT / "artifacts" / "phase2"


def _load_cases() -> dict[str, dict]:
    data = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    return {c["id"]: c for c in data["cases"]}


def _save_cases(cases: dict[str, dict]) -> None:
    CASES_PATH.write_text(
        json.dumps({"cases": list(cases.values())}, indent=2) + "\n", encoding="utf-8"
    )


def run_case(case: dict) -> int:
    case_id = case["id"]
    if case["status"] != "candidate":
        print(f"[{case_id}] skip: status is {case['status']!r}, not 'candidate'")
        return 2
    if (WORKDIR_ROOT / case_id).exists():
        print(f"[{case_id}] workdir exists; delete {WORKDIR_ROOT / case_id} first")
        return 2

    print(f"[{case_id}] cloning {case['source']} @ pinned commit")
    repo = clone_pinned(case["source"], case["commit"], WORKDIR_ROOT)

    print(f"[{case_id}] building clean venv")
    venv = make_pinned_venv(repo.root)

    ledger = RunLedger(ART_ROOT / case_id)
    art_dir = ART_ROOT / case_id

    print(f"[{case_id}] pinned install: {case['old_pin']}")
    pip_install(venv, case["old_pin"], "pytest", timeout_s=900.0)
    for pin in case.get("pre_install_pins", []):
        print(f"[{case_id}] pre-install pin: {pin}")
        pip_install(venv, pin, timeout_s=900.0)
    if case.get("install_repo", False):
        print(
            f"[{case_id}] installing target repo itself: {case.get('repo_install_args', ['-e', '.'])}"
        )
        pip_install(venv, *case.get("repo_install_args", ["-e", "."]), timeout_s=900.0)

    print(f"[{case_id}] pre-bump pytest (expect GREEN)")
    pre = verify(repo, venv, timeout_s=600.0, ledger=ledger, label=f"{case_id}/pre")
    save_outcome(pre, art_dir)
    print(f"[{case_id}] pre status: {pre.status.value} (exit {pre.result.exit_code})")
    if pre.status is not VerifyStatus.GREEN:
        print(f"[{case_id}] REJECTED: baseline is not GREEN; no case recorded.")
        return 3

    print(f"[{case_id}] bumping {case['dep']} -> {case['new_pin']}")
    try:
        pip_install(venv, f"{case['dep']}=={case['new_pin']}", timeout_s=600.0)
    except Exception as exc:  # the bump install itself failing IS evidence
        print(f"[{case_id}] bump install failed: {type(exc).__name__}: {exc}")
        from upgradepilot.models import PytestResult
        from upgradepilot.run_ledger import new_run_id

        post_run_id = new_run_id()
        post = VerifyOutcome(
            status=VerifyStatus.ENV_FAIL,
            run_id=post_run_id,
            result=PytestResult(exit_code=-2, output_tail=[f"{type(exc).__name__}: {exc}"]),
            reasons=[f"post-bump install failed: {type(exc).__name__}: {exc}"],
        )
        save_outcome(post, art_dir)
        case["status"] = "verified-passing-to-failing"
        case["commit"] = repo.commit
        case["verified"] = {
            "pre": pre.status.value,
            "post": post.status.value,
            "post_mode": "install-failure",
            "pre_run_json": str((art_dir / f"{pre.run_id}_*.json").relative_to(REPO_ROOT)),
            "post_run_json": str((art_dir / f"{post.run_id}_*.json").relative_to(REPO_ROOT)),
            "events": str((art_dir / "events.jsonl").relative_to(REPO_ROOT)),
        }
        merged = _load_cases()
        merged[case_id] = case
        _save_cases(merged)
        print(f"[{case_id}] VERIFIED (install-failure) case recorded in bench/cases.json")
        return 0

    print(f"[{case_id}] post-bump pytest (expect STUCK/ENV_FAIL)")
    post = verify(repo, venv, timeout_s=600.0, ledger=ledger, label=f"{case_id}/post")
    save_outcome(post, art_dir)
    print(f"[{case_id}] post status: {post.status.value} (exit {post.result.exit_code})")

    if post.status is not VerifyStatus.GREEN:
        case["status"] = "verified-passing-to-failing"
        case["commit"] = repo.commit  # exact SHA the verification ran at
        case["verified"] = {
            "pre": pre.status.value,
            "post": post.status.value,
            "pre_run_json": str((art_dir / f"{pre.run_id}_*.json").relative_to(REPO_ROOT)),
            "post_run_json": str((art_dir / f"{post.run_id}_*.json").relative_to(REPO_ROOT)),
            "events": str((art_dir / "events.jsonl").relative_to(REPO_ROOT)),
        }
        merged = _load_cases()
        merged[case_id] = case
        _save_cases(merged)
        print(f"[{case_id}] VERIFIED case recorded in bench/cases.json")
        return 0
    print(f"[{case_id}] NOT REPRODUCED (post status {post.status.value}); candidate kept.")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="list cases and statuses")
    parser.add_argument("--case", help="verify one case by id")
    args = parser.parse_args(argv)

    cases = _load_cases()
    if args.list:
        for cid, c in cases.items():
            print(f"{cid:28s} {c['status']:28s} {c['dep']} {c['old_pin']} -> {c['new_pin']}")
        return 0
    if not args.case:
        parser.error("either --list or --case <id> required")
    if args.case not in cases:
        print(f"unknown case {args.case!r}")
        return 2
    return run_case(cases[args.case])


if __name__ == "__main__":
    sys.exit(main())
