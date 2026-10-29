# UpgradePilot — Architecture

UpgradePilot upgrades **one** Python dependency in a repository and proves the
result with recorded evidence. This document describes how the pieces fit
together and which invariants the design enforces.

## Design principles

1. **Evidence over claims.** Every status, price, and benchmark row is backed
   by a raw artifact on disk (`artifacts/`). Nothing is summarised from
   memory or hand-written into a report.
2. **The user's repo is never touched.** Each run works in a disposable copy
   (`prepare.py`) with its own pinned virtualenv. The original checkout is
   read-only input.
3. **Tests are not editable.** The guard hashes the test surface before any
   model call and compares after every patch; a violation is `CHEATED`, not a
   pass.
4. **Fail closed.** Missing keys, unpriced models, concurrent runs, cost-cap
   breaches, and unknown statuses all abort with an explicit error rather
   than an optimistic result.

## High-level flow

```text
CLI (cli.py)                     Web (web/app.py + web/runs.py)
   |                                        |
   +------------ prepare_target() ----------+   prepare.py
                    |
        disposable repo copy + pinned venv
                    |
              run_upgrade()                    agent.py
                    |
   +---------+------+------+--------+---------+
   |         |             |        |         |
 held-out   guard       baseline  triage ->  patch -> verify
 split      snapshot     verify   research   loop (checkpoints,
 heldout.py guard.py     verify.py llm.py    rollback, escalation)
                                        |
                                   certify (visible GREEN -> held-out
                                   restore -> re-verify -> guarded status)
                                        |
                        UpgradeReport + proof_card.md + events.jsonl
```

The CLI and the web app are thin shells around the same pipeline: both call
`prepare_target()` and `run_upgrade()`, so a browser run and a terminal run
produce byte-comparable evidence.

## One run, stage by stage (`agent.py::run_upgrade`)

0. **Preparation** (`prepare.py`) — copy the checkout, build a venv, install the
   project's own pins, then explicitly install the old pin, run the suite as the
   **old-pin reference**, and only then install the bump. Resolved Python,
   pytest and package versions are read from the venv with `importlib.metadata`
   and written to `setup.json` and the report.
1. **Held-out split** (`heldout.py`) — real test modules only (never configs
   or conftest) are split deterministically by `sha256(path)`, so visible and
   held-out sets are disjoint, complete, and reproducible across runs.
2. **Guard baseline** (`guard.py`) — hashes every test-surface file into
   `guard_baseline.json`. Every later certification compares to this snapshot.
3. **Physical quarantine** — held-out files are moved *outside* the worktree
   into `heldout_quarantine/` so the model cannot see or edit them. They are
   restored before certification and on every exit path.
4. **Baseline verify** — the visible suite runs before any change. A baseline
   that is already GREEN short-circuits to certification (no pointless
   patching); a baseline `ENV_FAIL` is still recorded honestly.
5. **Triage (cheap tier)** — classifies the failure and produces a search
   query. No application source files means `ENV_FAIL` immediately.
6. **Research** — Tavily search for migration/changelog context, every run,
   even when the query is a fallback.
7. **Patch → guard → verify loop** — for up to `max_iterations`:
   - capture a `RepoCheckpoint` (byte-level snapshot minus venv/git/caches),
   - apply the model's patch (`editing.py`) to source files only,
   - hash the test surface: a guard violation rolls the checkpoint back and
     ends the run as `CHEATED`,
   - run pytest through `harness.py` (config-isolated: child runs pin their
     own config file so our `pyproject.toml` cannot leak in),
   - compare skipped/xfailed counts against the **old-pin reference** (the
     pre-bump GREEN run), not the post-bump baseline: a run that never
     collected has no meaningful skip profile,
   - any non-GREEN outcome restores the checkpoint, so the tree always holds
     the best attempt so far, and the log states the real reason with actual
     statuses and counts (no sentinel values),
   - escalate `default` → `strong` after `escalate_after` failed attempts.
8. **Certification** — only a visible GREEN can be certified: quarantine is
   restored, the held-out subset runs, `heldout_status()` folds visible +
   held-out verdicts (`OVERFIT` when visible passes but held-out fails), and
   `guarded_status()` overlays the guard verdict.
9. **Proof card** — `proof_card_markdown(report)` is written to
   `proof_card.md` next to `upgrade_report.json`; every step and cost record
   is appended to `events.jsonl` as it happens.

### Status vocabulary

| Status | Meaning | Source |
|--------|---------|--------|
| `GREEN` | pytest classification passed | `verify.py` |
| `STUCK` | ran, did not pass | `verify.py` |
| `ENV_FAIL` | environment/setup failure | `verify.py` |
| `CHEATED` | test surface modified during a patch | `guard.py` |
| `OVERFIT` | visible tests pass, held-out tests fail | `heldout.py` |

## Module map

| Module | Responsibility |
|--------|----------------|
| `prepare.py` | copy the target checkout, build a pinned venv, write `setup.json` |
| `agent.py` | the loop above, `UpgradeReport`, proof-card rendering |
| `pipeline.py` | stable re-export of the loop for CLI and web |
| `harness.py` | venv creation, pinned installs, pytest runner with config isolation |
| `verify.py` | classify pytest output into the status vocabulary |
| `guard.py` | test-surface hashing, path protection, `CHEATED` verdicts |
| `heldout.py` | deterministic held-out split and folded verdicts |
| `checkpoints.py` | byte-level repo snapshot / restore for rollback |
| `editing.py` | apply model patches, restricted to source files |
| `llm.py` | chat client, retries, per-run USD cap, post-hoc usage booking |
| `catalog.py` / `tiers.py` | live catalog fetch and tier policy (prices from catalog only) |
| `research.py` | Tavily client |
| `run_ledger.py` | append-only JSONL event log |
| `models.py` | token usage, cost records, `PytestResult` |
| `config.py` / `secrets.py` | settings from `.env`, fail-fast key checks, key masking |
| `cli.py` | `doctor` / `catalog` / `upgrade` / `bench` / `site` / `web` |
| `site.py` | static recorded-runs site generated only from artifact JSON |
| `web/app.py` | FastAPI app factory and endpoints |
| `web/runs.py` | run orchestration and artifact reads for the web layer |

## Money and models

- Model **choice** is configuration; model **price and context** come from
  the live Token Factory catalog on every run. A configured model that is
  absent, inactive, or unpriced in the catalog fails the run closed.
- Before each request the per-run USD cap is enforced; after each response
  exact usage is booked to `report.cost` and to the ledger (`llm_cost`
  events).
- NVIDIA NIM publishes no machine-readable prices, so NIM runs are recorded
  as **unpriced** with a call-count cap — no dollar figure is invented.
  NIM is development-only; Token Factory is the submission path.

## Artifacts

```text
artifacts/runs/<run_id>/
  events.jsonl           append-only step/cost ledger (SSE replays this)
  setup.json             checkout + venv build evidence
  guard_baseline.json    test-surface hashes before any edit
  test_split.json        visible/held-out split proof
  upgrade_report.json    full UpgradeReport (steps, attempts, costs, status)
  proof_card.md          human-readable proof card
artifacts/phase2/<case>/   benchmark evidence (pre-GREEN, post-broken runs)
artifacts/phase5/<case>/   strategy comparison rows (provider, models, versions)
artifacts/demo/            demo-case preconditions, strategy rows, held-out runs
artifacts/phase0/          catalog/doctor/live-call evidence
```

`bench/results_table.py` renders the benchmark table **only** from raw
`run-*.json` artifacts; missing evidence renders as an em dash, never as an
assumed value.

## Web layer (Phase 6)

FastAPI app factory (`web/app.py`) serving a static, no-build single-page UI
plus JSON and SSE endpoints (see README for the route table). Concurrency
model: a single worker thread per run guarded by an in-process busy flag —
`POST /api/runs` returns 409 while a run is active; the SSE stream first
replays `events.jsonl` from disk, then tails it until the run's terminal
event. `GET /healthz` is the Phase 0 liveness contract and must stay
dependency-free.

## Recorded-runs site (`site.py`)

`upgradepilot site build` reads the three artifact families above and writes
`docs/`: one page per recorded run (timeline, proof card, provider, resolved
environment, raw JSON link), a comparison page that keeps benchmark and demo
rows in separate tables, and an about page. Files that cannot be parsed are
listed on the home page instead of being skipped, and an artifact directory with
no runs renders an explicit empty state. There is no JavaScript; light/dark
follows `prefers-color-scheme`, tables scroll horizontally with a labelled,
focusable region, and every status is text + colour.

## Testing strategy

- **Offline by default:** `pytest tests` (`-m 'not live'`) — unit tests plus
  real subprocess tests for git/venv/pip/pytest, 194 tests. Offline tests are
  isolated from the developer's `.env` by `tests/conftest.py`, so switching
  providers locally cannot change their results.
- **Live tests opt-in:** `-m live` makes real provider/Tavily calls, self-skips
  without the active key, and writes raw request/response evidence to
  `artifacts/phase0/live_calls/`.
- **Gates:** `ruff check .`, `ruff format --check .`, `mypy src tests`, and a
  CI coverage floor of 70%.
