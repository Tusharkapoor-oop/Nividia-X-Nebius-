"""Build a markdown results table from raw benchmark JSON artifacts.

Reads ``artifacts/phase2/<case_id>/run-*.json`` files produced by
``bench/verify_case.py`` and renders a markdown table with one row per case,
showing pre-bump and post-bump status plus key pytest metrics.

Only raw artifact JSONs are consumed — nothing is claimed that isn't backed
by a recorded run.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_RUN_RE = re.compile(r"^run-(?P<run_id>.+?)_(?P<status>green|stuck|env_fail)\.json$")


def _load_case_results(art_dir: Path) -> dict[str, dict]:
    """Return {case_id: {pre: {...}, post: {...}}} from artifact run JSONs."""
    results: dict[str, dict] = {}
    if not art_dir.is_dir():
        return results

    for case_dir in sorted(art_dir.iterdir()):
        if not case_dir.is_dir():
            continue
        case_id = case_dir.name
        pre: dict | None = None
        post: dict | None = None
        for json_path in sorted(case_dir.glob("run-*.json")):
            m = _RUN_RE.match(json_path.name)
            if not m:
                continue
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            label = m.group("status")
            entry = {
                "run_id": data.get("run_id", ""),
                "status": data.get("status", ""),
                "exit_code": data.get("result", {}).get("exit_code", -1),
                "passed": data.get("result", {}).get("passed", 0),
                "failed": data.get("result", {}).get("failed", 0),
                "errors": data.get("result", {}).get("errors", 0),
                "duration_s": data.get("result", {}).get("duration_s", 0.0),
                "reasons": data.get("reasons", []),
            }
            if label == "green":
                pre = entry
            elif label in {"env_fail", "stuck"}:
                post = entry
        results[case_id] = {"pre": pre, "post": post}
    return results


def build_results_table(art_root: Path) -> str:
    """Return a markdown table summarising all benchmark case results."""
    results = _load_case_results(art_root)

    lines: list[str] = []
    lines.append("# Benchmark Results")
    lines.append("")
    lines.append(
        "Generated from raw JSON artifacts under ``artifacts/phase2/<case>/``. "
        "Nothing is claimed without a recorded run."
    )
    lines.append("")
    lines.append(
        "| Case | Pre (baseline) | Post (after bump) | Exit pre | Exit post | Passed pre | Failed/Errors post | Duration post |"
    )
    lines.append(
        "|------|----------------|-------------------|----------|-----------|------------|--------------------|---------------|"
    )

    if not results:
        lines.append("| *no cases found* | *—* | *—* | *—* | *—* | *—* | *—* | *—* |")
        return "\n".join(lines)

    for case_id in sorted(results):
        entry = results[case_id]
        pre = entry["pre"]
        post = entry["post"]

        pre_status = pre["status"] if pre else "—"
        post_status = post["status"] if post else "—"
        pre_exit = str(pre["exit_code"]) if pre else "—"
        post_exit = str(post["exit_code"]) if post else "—"
        pre_passed = str(pre["passed"]) if pre else "—"
        post_fe = f"{post['failed']}F/{post['errors']}E" if post else "—"
        post_dur = f"{post['duration_s']:.2f}s" if post else "—"

        lines.append(
            f"| {case_id} | {pre_status} | {post_status} | {pre_exit} | {post_exit} | "
            f"{pre_passed} | {post_fe} | {post_dur} |"
        )

    lines.append("")
    lines.append(
        "Legend: Pre = pytest run before the dependency bump (expect GREEN). "
        "Post = pytest run after the single dependency bump (expect STUCK/ENV_FAIL)."
    )
    return "\n".join(lines)


def build_results_table_json(art_root: Path) -> list[dict]:
    """Return the results data as a list of dicts (for programmatic use)."""
    results = _load_case_results(art_root)
    rows: list[dict] = []
    for case_id in sorted(results):
        entry = results[case_id]
        pre = entry["pre"]
        post = entry["post"]
        rows.append(
            {
                "case_id": case_id,
                "pre_status": pre["status"] if pre else None,
                "post_status": post["status"] if post else None,
                "pre_exit_code": pre["exit_code"] if pre else None,
                "post_exit_code": post["exit_code"] if post else None,
                "pre_passed": pre["passed"] if pre else None,
                "post_failed": post["failed"] if post else None,
                "post_errors": post["errors"] if post else None,
                "post_duration_s": post["duration_s"] if post else None,
            }
        )
    return rows
