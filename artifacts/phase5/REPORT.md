# UpgradePilot — Phase 5 report: the agent against real baselines

Written 2026-10-27. Provider for every LLM call below: **NVIDIA NIM**
(`nvidia-nemotron-3.5-lightning-30b-a3b` default/cheap tier,
`nvidia-nemotron-3-ultra-550b-a55b` strong/escalation tier), which is a
development-only provider — not the submission-eligible one. Tavily research
was live. Nothing in this report is estimated or extrapolated: every number is
read out of the JSON artifacts listed in Appendix A.

## 0. Bottom line

1. The comparison harness exists and works: **8 rows, 4 strategies × 2
   verified cases**, all from real runs (`bench/compare.py` →
   `artifacts/phase5/`).
2. **No strategy reached GREEN on either case — including the agent loop.** 6
   of 8 rows are `ENV_FAIL`, 1 is `STUCK`, 1 is `CHEATED`.
3. **The repository still contains no certified GREEN agent run at all.**
   Across every `proof_card.md` in the tree the verdicts are `STUCK`,
   `ENV_FAIL`, `CHEATED` (Section 6.5).
4. Two real defects turned up while reading the evidence, both in how a
   *failing-on-collection* baseline is handled: a likely false `CHEATED`
   (Section 7.1) and a rollback message that states the wrong reason
   (Section 7.2).
5. The honest submission story today is **"proof-first, and it does not
   pretend"**: the loop refuses to certify a patch that skips tests, rolls back
   every patch that does not improve the suite, and leaves the target repo
   byte-identical when it cannot win. It has not yet demonstrated a *win*, and
   the demo must not imply one.

## 1. What was built

| Component | Path | What it does |
|---|---|---|
| Strategy comparison runner | `bench/compare.py` (498 lines) | Runs `bump-only`, `codemod`, `single-shot`, and `agent` against one pinned checkout per case; writes one `result.json` per row plus `results.md` |
| Generated table | `artifacts/phase5/results.md` | Markdown table rendered only from recorded rows (`--table-only`) |
| Plugin-load screen | `bench/plugin_load_screen.py` | Rerunnable screen of pre-pytest-8 plugin releases against a modern pytest |
| Saved screen output | `artifacts/phase2/plugin_load_screen.txt` | 11 releases, 0/11 fail to load under pytest 8.4.1 |

Strategy definitions, as implemented — not as hoped:

- **bump-only** — the control. Install the new dependency, run the suite, record
  the outcome. No repair.
- **codemod** — deterministic regex renames from a documented table
  (Pydantic v1 → v2). No model call. Ambiguous renames (`.dict()`, `.json()`,
  `.copy()`) are **deliberately excluded**, because a plain `dict` has those
  names too and rewriting them would break code the bump never touched. When no
  table exists for the bump, the row says so and equals the control.
- **single-shot** — exactly one model patch attempt: no triage, no research, no
  iteration. Failure output is captured once, one prompt is sent, the returned
  files are applied through the same validator the agent uses, and the suite is
  run once.
- **agent** — the full Phase 4 loop: triage (cheap tier) → Tavily research →
  held-out quarantine → patch (default tier, escalating to strong) → guard →
  verify → certify, with checkpoint/rollback on failure.

Both non-control strategies are subject to the same test-surface guard, so a
strategy that "fixes" the suite by touching tests is recorded as `CHEATED`
rather than credited.

## 2. Method and reproduction

```powershell
# one case, all four strategies (this is what produced this report)
.\.venv\Scripts\python.exe bench\compare.py --case pydantic-argparse-pydantic1-to-2
.\.venv\Scripts\python.exe bench\compare.py --case pytest-lazy-fixture-pytest7-to-8

# regenerate the table from the recorded rows only
.\.venv\Scripts\python.exe bench\compare.py --table-only
```

For each `(case, strategy)` pair the runner:

1. clones the case repo at its pinned commit into `bench/workdirs/cases/<id>/`
   (git-ignored, disposable);
2. copies that checkout into `bench/workdirs/phase5/<case>--<strategy>/` and
   builds a fresh venv there, installing the case's `new_pin` last
   (`upgradepilot.prepare.prepare_target`);
3. applies the case's `pre_install_pins`;
4. snapshots the test surface for the guard;
5. runs the post-bump suite once (`bump-only`) and records it;
6. performs the strategy's repair (if any) and re-runs the suite;
7. compares guard snapshots, folds the result into the status
   (`guarded_status`), and writes
   `artifacts/phase5/<case>/<strategy>/result.json`, the pytest outcome JSONs,
   and a copy of the run ledger.

Bulky checkouts and venvs never enter git: only the JSON/markdown evidence is
committed (47 files including this report, all small).

## 3. Environment, provenance, and what is *not* pinned

| Item | Value |
|---|---|
| Interpreter (case venvs) | Python 3.13.15 (Windows) |
| Case dependency under test | `pytest==8.4.1` / `pydantic==2.12.4` (the case `new_pin`, installed last) |
| LLM provider | NVIDIA NIM, development-only, **unpriced** |
| Models used | `nvidia/nemotron-3.5-lightning-30b-a3b` (triage/default), `nvidia/nemotron-3-ultra-550b-a55b` (strong, after escalation) |
| Research provider | Tavily, live |
| Tool versions inside the case venvs | **not recorded** (see finding D4) |

Cost: **unpriced by design**. NIM publishes no machine-readable price catalog,
so the rows record call counts and token counts and `cost_usd: null`; the tool
never converts unpriced calls into invented dollars. Total consumption across
all 8 rows: **10 LLM calls, 30,691 prompt tokens, 6,036 completion tokens**.

## 4. Cases under test

| Case id | Repo (pinned) | Bump | Breakage mechanism |
|---|---|---|---|
| `pydantic-argparse-pydantic1-to-2` | `SupImDos/pydantic-argparse` @ `c07199879040` (0.8.0, MIT) | `pydantic==1.10.22` → `2.12.4` | v1-only code paths: `pydantic.fields.ModelField` and `pydantic.fields` no longer resolve |
| `pytest-lazy-fixture-pytest7-to-8` | `TvoroG/pytest-lazy-fixture` @ `18ec85edb5e2` (MIT) | `pytest==7.4.4` → `8.4.1` | plugin hooks use the removed `CallSpec2.funcargs` API; collection aborts |

Both are *hard* cases by construction: the first is a whole-major-version
migration of the library the repo is built on, the second is a plugin whose
core mechanism pytest 8 removed.

## 5. Results

Generated table: `artifacts/phase5/results.md`.

| Case | Strategy | Status | Suite | Iters | LLM calls | Tokens (in/out) | Wall |
|---|---|---|---|---|---|---|---|
| pydantic-argparse | bump-only | ENV_FAIL | exit 4, 0P/0F/0E | 0 | 0 | 0/0 | 37.1s |
| pydantic-argparse | codemod | ENV_FAIL | exit 4, 0P/0F/0E | 0 | 0 | 0/0 | 31.3s |
| pydantic-argparse | single-shot | ENV_FAIL | exit 4, 0P/0F/0E | 0 | 1 | 13,354/873 | 46.4s |
| pydantic-argparse | agent | ENV_FAIL | exit 4, 0P/0F/0E | 5 | 6 | 10,367/1,627 | 75.5s |
| pytest-lazy-fixture | bump-only | ENV_FAIL | exit 2, 0P/0F/1E | 0 | 0 | 0/0 | 42.0s |
| pytest-lazy-fixture | codemod | ENV_FAIL | exit 2, 0P/0F/1E | 0 | 0 | 0/0 | 35.7s |
| pytest-lazy-fixture | single-shot | **STUCK** | exit 1, 0P/0F/0E | 0 | 1 | 2,776/1,774 | 67.4s |
| pytest-lazy-fixture | agent | **CHEATED** | exit 2, 0P/0F/1E | 1 | 2 | 4,194/1,762 | 106.3s |

Totals: 441.7 s (7 min 22 s) wall, 10 LLM calls, 30,691 prompt + 6,036
completion tokens, 0 GREEN rows. `suite_duration_s` is 0.0 on the
pydantic-argparse rows because pytest exits with a usage error (4) before
printing a summary line, and the parser refuses to fabricate one.

## 6. Row-by-row evidence

### 6.1 `pydantic-argparse` — all four strategies

Post-bump failure, from
`pydantic-argparse-pydantic1-to-2/bump-only/bump-only/run-20261027T112342-5f3f03_env_fail.json`:

```
def name(field: pydantic.fields.ModelField, invert: bool = False) -> str:
E   AttributeError: module 'pydantic' has no attribute 'fields'. Did you mean: 'Field'?
```

- **bump-only** — `ENV_FAIL`, exit 4. The control: collection dies on an import.
- **codemod** — applied 11 mechanical rules to **1 file**
  (`pydantic_argparse/argparse/parser.py`) and the suite still fails at
  collection, with the identical error, because the failing import lives in
  `utils/arguments.py` and contains no rename the table covers. Recorded diff
  count: `artifacts/phase5/.../codemod/result.json` → `edits`.
- **single-shot** — 1 call, 13,354 tokens in, 873 out; wrote 2 files
  (`pydantic_argparse/utils/arguments.py`, `pydantic_argparse/utils/types.py`).
  Outcome still `ENV_FAIL`, but the error moved *within* the same file
  (`module 'pydantic.fields' has no attribute 'ModelField'`) — the patch touched
  the right area and did not finish the migration.
- **agent** — 5 iterations, 6 calls, guard reported *clean* after every attempt
  (test surface untouched), and **every patch was rolled back**:
  `attempts/attempt_01..05_rolled_back.json`. Tier escalation is visible in the
  ledger: attempts 1–2 on `lightning`, attempts 3–5 on `ultra`. Verdict
  `ENV_FAIL`. Proof card:
  `.../agent/pydantic-argparse-pydantic1-to-2--agent/proof_card.md`.
  Triage query: `'pydantic fields module removed pydantic 2 migration'`;
  Tavily returned 3,318 chars of context.

### 6.2 `pytest-lazy-fixture` — bump-only, codemod

```
Plugin: lazy-fixture, Hook: pytest_generate_tests
AttributeError: 'CallSpec2' object has no attribute 'funcargs'
!!!! Interrupted: 1 error during collection !!!!
```

Both rows are `ENV_FAIL` (exit 2, 1 collection error). The codemod row is
explicitly labelled as the control by the runner: *"no mechanical rename table
for pytest pytest==7.4.4 -> 8.4.1; codemod is the control."*

### 6.3 `pytest-lazy-fixture` — single-shot

1 call, 2,776 in / 1,774 out; wrote `pytest_lazyfixture.py`. The status moved
`ENV_FAIL` → **`STUCK`** (exit 1): the plugin now loads far enough that pytest
runs, and the recorded tail shows a new, self-inflicted failure:

```
pluggy._manager.PluginValidationError: Plugin 'lazy-fixture' for hook 'pytest_runtest_call'
hookimpl definition: pytest_runtest_call(item)
Declared as wrapper=True or hookwrapper=True but function is not a generator function
```

i.e. the single attempt removed the offending hook but left the wrapper
declaration behind. This is the clearest evidence in the whole set that one
shot is not enough for this class of breakage: the model got closer and broke
something else.

### 6.4 `pytest-lazy-fixture` — agent: the `CHEATED` row

1 iteration, 2 calls (triage + one patch), 4,194 in / 1,762 out. Sequence from
the ledger (`.../agent/pytest-lazy-fixture-pytest7-to-8--agent/events.jsonl`)
and the attempt artifact:

1. `heldout_split`: 1 visible, 0 held-out test file.
2. `guard_snapshot`: 4 test-surface files hashed.
3. `baseline_verify`: breakage confirmed, `ENV_FAIL`.
4. `triage` → query `'pytest CallSpec2 funcargs attribute removed migration guide'`.
5. `research` → Tavily, 3,947 chars.
6. `patch_attempt_1` → `lightning` wrote `pytest_lazyfixture.py` (diff kept in
   `attempts/attempt_01_guard_violation.json`): it deleted the
   `pytest_runtest_call` hook and dropped
   `normalize_metafunc_calls(metafunc, 'funcargs')`.
7. `guard_check_1` → **failed**: "1 newly skipped test(s) (baseline: 0,
   current: 1)" and "1 newly xfailed test(s) (baseline: 0, current: 1)".
8. The file was **rolled back** and the run certified `CHEATED`.

The patch never touched a test file (the guard's file-hash check was clean, 4
files unchanged). What it did was *disable* plugin behaviour, and the count of
skipped/xfailed tests moved — which is exactly the signal the guard treats as
test-masking. Whether that verdict is right in this instance is finding 7.1.

### 6.5 The missing GREEN

Every certified run in the repository:

| Artifact | Verdict | Iterations | Calls |
|---|---|---|---|
| `artifacts/runs/run-20261023T034032-c06f8b/upgrade_report.json` | `STUCK` | 5 | 6 |
| `artifacts/phase5/pydantic-argparse-pydantic1-to-2/agent/.../upgrade_report.json` | `ENV_FAIL` | 5 | 6 |
| `artifacts/phase5/pytest-lazy-fixture-pytest7-to-8/agent/.../upgrade_report.json` | `CHEATED` | 1 | 2 |

There is no GREEN run to show. This is not a reporting gap: the tool has never
certified a successful upgrade, and the Phase 2 case set (2 verified cases, both
hard migrations) plus the benchmark table cannot demonstrate success.

## 7. Findings

### D1 — Possible false `CHEATED` when the baseline never collected (High)

`guard.check_skipped_or_xfailed()` compares summary counts only:

```python
if current_result.skipped > baseline_result.skipped:
    ...
if current_result.xfailed > baseline_result.xfailed:
    ...
```

When the bump breaks *collection* — the most common upgrade failure — the
baseline reports `0 skipped / 0 xfailed`, so **any** skip or xfail in a later run
is "newly skipped", even when it comes from a behaviour change in patched source
rather than from an edited test. That is what happened to the agent's only patch
in this set (Section 6.4).

Effect: a run can be certified `CHEATED` on a comparison against a baseline that
produced no results at all. Evidence:
`artifacts/phase5/pytest-lazy-fixture-pytest7-to-8/agent/pytest-lazy-fixture-pytest7-to-8--agent/attempts/attempt_01_guard_violation.json`.

Suggested fix: skip both comparisons when the baseline has no results
(`PytestResult.collected_anything` already exists), and record in the guard
report that the check was not applicable. That keeps the anti-masking rule for
the case it was written for (a suite that already ran) and stops it firing on
non-collecting baselines. **Not implemented** — it changes certification
semantics and is your call.

### D2 — Rollback message names the wrong reason (Medium)

`agent.py` records a rolled-back attempt as:

```
Visible tests did not improve (exit 4, 0 failed >= 999999); rolled back 1 file(s)
```

That text is misleading twice over: `999999` is the sentinel set when the
baseline is *not* `STUCK`, and the real determining condition was the status
(`ENV_FAIL` — the patched suite still could not collect), not a failure-count
comparison. A reader — or a judge watching the demo — sees nonsense arithmetic
where the true reason should be. Recorded in all five
`attempts/attempt_0*_rolled_back.json` and in the ledger for the pydantic case.
Suggested fix: phrase the message from the actual branch (status not improved /
failed count did not decrease), and print the status, not the sentinel.

### D3 — The benchmark cannot show a win (High, scope rather than code)

Both verified cases are hard migrations (Section 4). The loop's own improvement
gate is reasonable (keep a patch only if the suite reaches GREEN, or the
collection problem is fixed and failures strictly decrease), but no case exists
where it can plausibly pay off. Until one does, every downstream artifact — the
web bench table, the Devpost text, the video — has to be written around a
negative result.

### D4 — Provenance gap in each row (Medium)

`result.json` records status, tokens, timings, guard state, and edit paths, but
not the resolved versions of the tools in the case venv, and
`prepare_target` does not apply the case's `old_pin`: it installs
`pytest`/`pytest-mock` unpinned and only then the case's `new_pin`. Consequence:
the Phase 5 environment is close to, but not identical with, the environment
`bench/verify_case.py` used for the Phase 2 verification, and the rows cannot
prove which pytest they ran. Suggested fix: write a `pip freeze` digest (or at
least the pytest/python versions) into each `result.json`.

### D5 — Baseline edits are not diffed into evidence (Low)

The agent path persists a full diff per attempt (`attempt_*.json`), but the
codemod and single-shot rows persist only file paths and counts. The single-shot
error quoted in Section 6.3 is reconstructable only from the pytest tail, not
from a stored diff. Suggested fix: persist `EditApplied.diff` for every
strategy's edits.

### D6 — Phase 2 still has 2 verified cases (Low, documented)

Re-attempted on 2026-10-27 with the earlier methodological flaw fixed (no more
`HEAD`-only clones):

- `pytest-subtests` pinned to tag `v0.11.0` (commit `06315b41`, its
  pre-pytest-8 release) measures **GREEN → GREEN** on pytest 8.4.1
  (`run-20261027T111728-05da6e_green.json`,
  `run-20261027T111739-bb11fd_green.json`).
- `pytest-check-links` @ `HEAD` has a non-GREEN baseline (`ENV_FAIL`, exit 2) and
  is rejected before any claim is made
  (`run-20261027T112107-37e36b_env_fail.json`).
- The load screen (`artifacts/phase2/plugin_load_screen.txt`) shows **0 of 11**
  pre-pytest-8 releases fail to collect under pytest 8.4.1, so "the plugin no
  longer loads" is not available as a reproduction path at this pytest version.

Conclusion: a third verified case needs a **source-level** breakage (a documented
API removal the repo's own code uses), not a plugin-load breakage.

## 8. What this means for the submission

- **Do not present a success.** Nothing in `artifacts/` supports a GREEN claim.
- The defensible pitch is the *proof discipline*, which the artifacts do
  support: held-out quarantine, hashed test surface, `CHEATED` on test
  manipulation, checkpoint rollback on every non-improving patch, per-run proof
  cards, and a case set that refuses to be promoted on a near-miss (13
  candidates stayed candidates).
- The strongest live demo material is *failure handling*: the guard rejecting a
  patch that weakens the suite (Section 6.4) and five escalated attempts being
  rolled back with the tree left untouched (Section 6.1).
- Cost claims stay honest: NIM is unpriced, so the report and UI say "unpriced",
  never a dollar figure. Token counts are real.

## 9. Verification performed

All four gates on the committed tree (before this report's commit, after the
Phase 5 code landed):

| Gate | Command | Result |
|---|---|---|
| Lint | `ruff check .` | 0 issues |
| Format | `ruff format --check .` | 91 files already formatted |
| Types | `mypy src tests` | 0 issues, 47 files |
| Tests | `pytest tests` | **175 passed, 4 deselected**, exit 0 |

Also verified in this session:

- the strategy runner end-to-end (8 rows above), including the `--table-only`
  regeneration path;
- the plugin-load screen end-to-end with its output persisted
  (`artifacts/phase2/plugin_load_screen.txt`);
- earlier on 2026-10-27, a fresh clone under a *different directory name* →
  `pip install -e ".[web,dev]"` → all four gates green (this caught and fixed a
  portability bug in `tests/test_config.py`).

Not verified, and not claimed: any Token Factory (Nebius) call — no
`NEBIUS_API_KEY` is configured (`doctor --json` passes on NVIDIA NIM only and
says so explicitly) — any dollar cost, and the demo video.

## 10. Open items, in the order I would take them

1. **Find one case the loop can solve** (source-level breakage: a documented API
   removal in a small permissive repo), then re-run this sweep and record the
   first GREEN row. Everything downstream depends on it.
2. **Decide D1**, then implement the guard change (skip/xfail compared only when
   the baseline collected something).
3. **Fix D2** (rollback message) — small, and it is the text a judge reads in the
   demo.
4. **Close D4** by recording the resolved environment in each row.
5. **Give the pytest 7→8 codemod a real rule family**, so that row stops being
   the control and the comparison has three meaningful arms.
6. Re-run Phase 5 against Token Factory once a Nebius key exists, so the
   submission path is what the table shows.

## Appendix A — artifact index

All paths are relative to `artifacts/phase5/`.

```
results.md                                  generated table (this report's Section 5)
pydantic-argparse-pydantic1-to-2/
  bump-only/{result.json,events.jsonl,bump-only/run-*_env_fail.json}
  codemod/{result.json,events.jsonl,bump-only/run-*_env_fail.json,final/run-*_env_fail.json}
  single-shot/{result.json,events.jsonl,bump-only/run-*_env_fail.json,final/run-*_env_fail.json}
  agent/{result.json,events.jsonl,bump-only/run-*_env_fail.json,
         pydantic-argparse-pydantic1-to-2--agent/{upgrade_report.json,proof_card.md,
           test_split.json,guard_baseline.json,baseline_env_fail.json,
           run-*_env_fail.json,attempts/attempt_01..05_rolled_back.json}}
pytest-lazy-fixture-pytest7-to-8/
  bump-only/{result.json,events.jsonl,bump-only/run-*_env_fail.json}
  codemod/{result.json,events.jsonl,bump-only/run-*_env_fail.json}
  single-shot/{result.json,events.jsonl,bump-only/run-*_env_fail.json,final/run-*_stuck.json}
  agent/{result.json,events.jsonl,bump-only/run-*_env_fail.json,
         pytest-lazy-fixture-pytest7-to-8--agent/{upgrade_report.json,proof_card.md,
           test_split.json,guard_baseline.json,baseline_env_fail.json,
           run-*_env_fail.json,attempts/attempt_01_guard_violation.json}}
```

Related, outside this directory:

```
artifacts/phase2/pytest-subtests-pytest7-to-8/run-20261027T1117*_green.json   Phase 2 re-attempt
artifacts/phase2/pytest-check-links-pytest7-to-8/run-20261027T112107-*_env_fail.json
artifacts/phase2/plugin_load_screen.txt                                      plugin-load screen
artifacts/runs/run-20261023T034032-c06f8b/                                   Phase 4 STUCK run
bench/compare.py, bench/plugin_load_screen.py, bench/verify_case.py          runners
bench/cases.json                                                             case set (15, 2 verified)
```

## Appendix B — raw numbers

| Metric | Value |
|---|---|
| Rows recorded | 8 (4 strategies × 2 cases) |
| GREEN / STUCK / ENV_FAIL / CHEATED rows | 0 / 1 / 6 / 1 |
| Total wall time | 441.7 s |
| LLM calls | 10 (6 agent-pydantic, 2 agent-lazy-fixture, 1+1 single-shot) |
| Prompt / completion tokens | 30,691 / 6,036 |
| Dollar cost | not claimed (provider unpriced) |
| Fastest row | pydantic codemod, 31.3 s (no LLM) |
| Slowest row | lazy-fixture agent, 106.3 s (includes rollback + certification) |
| Cases verified (Phase 2) | 2 of 15, unchanged |
| Repo-wide test suite (2026-10-29) | 195 passed, 4 deselected |

---

## Addendum — post-fix re-run (2026-10-28)

The Phase 5 rows above were produced before the D1, D2 and D4 fixes. This
addendum records the re-run and does not rewrite the original observations.

**What changed in the harness (commit `a654660` and the prompt fix after it):**

- **D1.** The skip/xfail masking check now compares against the **old-pin GREEN
  run** recorded before the bump (`reference_outcome`), not the post-bump
  baseline. Every row now also records that reference run.
- **D2.** Rollback messages state the real comparison ("still STUCK with 33
  failing test(s), not fewer than the best 33 seen so far") instead of printing
  the `999999` sentinel.
- **D4.** `prepare_target` installs the old pin before the bump, and every row
  records the resolved Python, pytest and upgraded-package versions read from
  the case venv. Rows also record `provider`, `run_class` and model IDs.
- The patch prompt gained one scope note (a traceback inside `tests/` is a
  symptom; test-surface edits end the run) after the demo case's first run
  ended `CHEATED`.

**Re-run results (`artifacts/phase5/results.md`):**

| Case | Strategy | Before | After |
|------|----------|--------|-------|
| pydantic-argparse-pydantic1-to-2 | bump-only / codemod / single-shot / agent | ENV_FAIL ×4 | ENV_FAIL ×4 |
| pytest-lazy-fixture-pytest7-to-8 | bump-only / codemod | ENV_FAIL / ENV_FAIL | ENV_FAIL / ENV_FAIL |
| pytest-lazy-fixture-pytest7-to-8 | single-shot | STUCK | STUCK |
| pytest-lazy-fixture-pytest7-to-8 | agent | **CHEATED** (D1 false positive) | **STUCK** — 12 passed, 33 failed |

The old-pin reference for `pytest-lazy-fixture` is GREEN with 45 passed, 1
skipped and 1 xfailed. That is exactly the skip/xfail profile D1 was about: the
repaired suite legitimately carries the same skip and xfail the original suite
had, so it is no longer labelled `CHEATED`. The run still does not reach GREEN —
the plugin breakage is not repairable by patching the fixture helper alone, and
the loop rolls back each attempt that does not reduce the failure count.

Benchmark verdict is unchanged: **0 of 8 rows reach GREEN**, and neither verified
case has a GREEN run at all. The demo case (`artifacts/demo/`) is where a GREEN
run exists; it is self-written and is not part of this table.

Resolved environment for both re-run cases: Python 3.13.15, pytest 9.2.0,
pydantic 2.12.4 (branch case: pytest 8.4.1). Provider: `nvidia-nim`, all rows
`run_class: dev`, unpriced (no invented USD).

## Verification update — 2026-10-29

- `pytest tests`: **195 passed, 4 deselected** (exit 0; 1 upstream deprecation warning).
- `ruff check src tests bench` and `ruff format --check src tests bench`: clean
  (the project source, test, and benchmark trees).
- `mypy src tests`: clean (50 source files).
- Root-level scratch scripts are excluded from those project checks and are not
  included in the public submission snapshot.
- `git diff --check`: passed.
