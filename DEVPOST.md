# Devpost submission text — UpgradePilot

Paste-ready text for the **Nebius x NVIDIA Global AI Hackathon** (Coding and
Agentic Engineering track). Every number below is copied from a file under
`artifacts/`; nothing is estimated.

---

## Project name

`UpgradePilot`

## Tagline

An AI agent that upgrades one Python dependency — and proves it worked instead
of claiming it did.

## Category

Coding and Agentic Engineering (select this track in the Devpost submission form).

## Submission assets — current state

- Repository target: <https://github.com/Tusharkapoor-oop/Nividia-X-Nebius->
  (currently empty; code has not been published there).
- Demo candidate: the static recorded-runs site in `docs/`; GitHub Pages is not
  deployed and no working public URL is available yet. It is explicitly a
  **recorded run**, not a live service.
- Video: `VIDEO.md` is a timed script for a cut under three minutes; recording
  and public YouTube upload are not done.
- Provider evidence: NIM artifacts stay labelled NVIDIA NIM development runs.
  Token Factory use is implemented but remains unverified until a real key and
  live calls are available.

---

## Long description

Dependency upgrades break software quietly: a version bumps, the suite stops
importing, and someone has to work out why. The usual agent "fix" is worse — it
edits the tests until they pass and reports green. Nothing was verified.

UpgradePilot upgrades **exactly one** Python dependency per run and turns the
result into evidence:

- **Old-pin reference.** Before the bump it installs and runs the project's own
  pins, recording a GREEN reference (30 passed on the demo case, 746 on
  `pydantic-argparse`). The reference is what skip/xfail counts are measured
  against; a post-bump run that never collected is not a valid baseline.
- **Test-suite guard.** Every test file, `conftest.py` and pytest config is
  hashed before the model sees the repo. Any edit is a violation: the checkpoint
  is restored and the run ends `CHEATED`.
- **Held-out checks.** Test modules are split deterministically by
  `sha256(path)`; the held-out half is physically moved outside the worktree
  while the model patches and is used only for certification. Visible GREEN +
  held-out failing is `OVERFIT`.
- **Rollback with a real reason.** Every attempt starts from a byte-level
  snapshot; a non-improving attempt is rolled back with the actual statuses and
  counts in the log ("still STUCK with 33 failing test(s), not fewer than the
  best 33 seen so far").
- **Proof card.** Each run writes `proof_card.md` and `upgrade_report.json` with
  provider, model IDs, resolved Python/pytest/package versions, commands, diffs,
  guard verdicts, visible vs held-out results, tokens and cost, replayed from an
  append-only `events.jsonl`.

### The demo case (self-written, not a benchmark)

`demo/invoicekit` is an original MIT invoice calculator pinned to pydantic
`1.10.22` with 30 tests. Bumping to `2.12.4` breaks the import
(`PydanticUserError: regex is removed`). Eleven behavioural assertions were
committed as an **external held-out contract** before the first agent run and are
never copied into the agent's work tree.

| Strategy | Status | Visible suite | Held-out contract |
|----------|--------|---------------|-------------------|
| bump-only | `ENV_FAIL` | 0 passed | `ENV_FAIL` |
| single-shot | `ENV_FAIL` | patch unparseable | `ENV_FAIL` |
| agent, first run | `CHEATED` | 0 passed | `ENV_FAIL` |
| agent, after one prompt fix | **`GREEN`** | 13 passed, 0 failed | **11 passed, 0 failed** |

The first agent run is included on purpose: the model tried to edit
`tests/conftest.py`, the guard rejected the patch and rolled it back, and the run
ended `CHEATED` instead of passing. The second run migrated
`src/invoicekit/models.py` only and certified GREEN in 3 iterations, 4 calls,
9,494 tokens.

### The honest benchmark result

`bench/compare.py` runs four strategies on the same pinned checkout of two
verified third-party cases. Eight real rows, **zero GREEN**:

- `pydantic-argparse` (pydantic 1.10.22 → 2.12.4): old pin GREEN with 746 tests;
  all four strategies end `ENV_FAIL` — a v1-only codebase is a migration, not a
  repair.
- `pytest-lazy-fixture` (pytest 7.4.4 → 8.4.1): old pin GREEN (45 passed, 1
  skipped, 1 xfailed); the plugin cannot load under pytest 8. The agent repairs
  collection and reaches `STUCK` with 12 passed / 33 failed; nothing reaches
  GREEN.

That is the result, and it is in the submission rather than hidden.

### Where Nemotron, Token Factory and Tavily are used

- **NVIDIA Nemotron (this build):** all model calls ran on **NVIDIA NIM**
  (`integrate.api.nvidia.com`) with `nvidia/nemotron-3.5-lightning-30b-a3b` for
  triage/patching and `nvidia/nemotron-3-ultra-550b-a55b` for escalation. These
  are **development runs**, labelled `provider: nvidia-nim`, `run_class: dev`.
- **Nebius Token Factory:** implemented and configured as the submission path —
  live catalog fetch, three priced tiers, per-run USD cap, pre/post accounting —
  but **no Token Factory call was made**: `NEBIUS_API_KEY` is empty in this
  build, so no Token Factory result is claimed anywhere.
- **Tavily:** used in every agent run for migration-guide research (live search
  verified 2026-10-21: 3 results, 1 credit, 3.44 s). The demo run's triage query
  was `pydantic 2.12 regex removed use pattern Field`.

### Verification

195 offline tests pass (`pytest tests`), 4 live tests are opt-in. `ruff check
src tests bench`, `ruff format --check src tests bench` and `mypy src tests` are
clean. Three untracked scratch scripts at the repo root are excluded from these
project checks. The recorded-runs site (`docs/`) is generated from artifact JSON
only and labels every row with its provider and timestamp. All recorded live
model calls in this build used NVIDIA NIM in development mode; no Token Factory
call has yet been made.

**Limitations, stated plainly:** no Nebius Token Factory call exists in this
build; the GREEN demo is a self-written case, not a generalisation claim; and
the two third-party benchmark cases remain unsolved migrations.

---

## Tech stack

- Python 3.11+, Typer/Rich CLI, pydantic v2 + pydantic-settings, httpx
- NVIDIA Nemotron 3 through NVIDIA NIM (development in this build)
- Nebius Token Factory (submission path: live catalog pricing, USD cap)
- Tavily search API
- pytest, Ruff, mypy, coverage; FastAPI + SSE for live runs
- Static, JavaScript-free HTML site generated from artifact JSON

## Repository

`https://github.com/Tusharkapoor-oop/Nividia-X-Nebius-` — MIT licensed
(`LICENSE`). `README.md` has setup and provider status; `PLAN.md` tracks each
phase with evidence pointers; `artifacts/` holds raw runs; `docs/` is the
recorded-runs site source for GitHub Pages. GitHub currently reports this target
repository as empty; publishing it remains pending.
