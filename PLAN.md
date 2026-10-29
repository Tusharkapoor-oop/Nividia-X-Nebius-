# UpgradePilot â€” PLAN.md

Track of the phase-by-phase build. Checked boxes are verified by real
output in this repo (test runs, CLI output, artifacts), not aspiration.

## Environment (verified 2026-10-20)

- Windows NT 10.0.26300, PowerShell 5.1
- Python 3.13.15 (`C:\Users\ACER\AppData\Local\Programs\Python\Python313\python.exe`),
  pip 26.2.1, uv 0.12.7
- git 2.55.0.windows.5
- Node 24.19.0 / npm 11.17.0 (not used by the app; no Node build step)
- GitHub CLI absent (needed later for Phase 7 publishing only)

## Token Factory tiers (verified against live catalog 2026-10-20)

Snapshot: `artifacts/phase0/catalog/models_info_snapshot_2026-10-20.json`
(raw response, 28 models, 5 NVIDIA entries, SHA256
`8527a31e3d6b1bbd6b8f241c95cd0f96d841b26ecdaef9f9fec2c5604c52cb8e`).
Verified with `upgradepilot doctor --json` + unit tests + live fetch.

| Role | model_id | ctx | $/M in | $/M out | licensed as |
|------|----------|-----|--------|---------|-------------|
| cheap / triage | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | 262,144 | 0.06 | 0.24 | nvidia-open-model-license |
| default / patch | `nvidia/Nemotron-3_5-Lightning` | 1,048,576 | 0.06 | 0.24 | OpenMDW v1.1 |
| strong / escalate | `nvidia/Nemotron-3-Ultra-550b-a55b` | 1,048,576 | 1.00 | 3.00 | openmdw-1.1 |

Notes:
- Model *choice* is policy (env vars); prices and context limits are read
  from the live catalog on every run via `build_tiers()`.
- The LLM client enforces a preflight per-run cost cap and books exact usage
  after each response.
- The catalog's `flavors[].label` is "cheap" across all flavors, so it is
  ignored for tiering â€” our policy drives tiers, not the label.

## Tavily (verified live 2026-10-21)

- `POST https://api.tavily.com/search` with `Authorization: Bearer tvly-...`
  returned 3 results for a pydantic 2.0 migration query, `credits=1`,
  `response_time=3.44 s`. Raw evidence:
  `artifacts/phase0/live_calls/tavily_search.json`.
- `doctor` performs a real Tavily search when the key is present; with Tavily
  configured and Nebius absent it reports `tavily search: ok` and still exits
  1 because the Nebius key is missing
  (`artifacts/phase0/doctor_tavily_only.json`).
- Depth/credit behaviour for `advanced` (2 credits) and 429/Retry-After
  handling remain UNVERIFIED until exercised.

## Provider decision (2026-10-21, updated)

Official hackathon rules (fetched from the Devpost rules page) require the
project to make a **runtime call to Nebius Token Factory** or run on Nebius AI
Cloud, plus use at least one NVIDIA open model. A key for NVIDIA's
`integrate.api.nvidia.com` endpoint is not a substitute.

**Decision:** build and test against NVIDIA NIM now because no Nebius key is
available yet, then switch the same pipeline to Token Factory before
submission. NIM is a **development-only** provider and is not eligible.
NIM publishes no machine-readable pricing catalog, so tiers are unpriced and
the run is capped by `MAX_LLM_CALLS_PER_RUN`; calls are recorded as unpriced,
never converted to invented dollars. Token Factory keeps its live-catalog
pricing and per-run USD cap.

NVIDIA NIM dev evidence (2026-10-21):

- `doctor --json` exit 0: `artifacts/phase0/doctor_nvidia_dev_2026-10-21.json`
- `pytest -m live` â†’ 4 passed in 69.08 s (3 tier calls + Tavily)
- artifacts: `artifacts/phase0/live_calls/nvidia_nim_{cheap,default,strong}.json`
- each live tier call: `finish_reason=stop`, 32 prompt + 2 completion tokens,
  content `OK`, `cost_usd=null`, `unpriced_calls=1`
- the trial NIM account exposes Lightning and Ultra; Nano/Super returned
  404/degraded, so dev mapping is cheap=default=Lightning, strong=Ultra
- NIM requests send `chat_template_kwargs={"enable_thinking": false}` so the
  answer is not consumed by reasoning tokens; Token Factory requests are
  unchanged
- spend: Token Factory **$0**; the three live-tier calls used **102 tokens**
  (NIM price not published, so no USD figure is claimed); Tavily searches are
  real and consume credits

### Submission switch (blocking)

Do not submit while `LLM_PROVIDER=nvidia-nim`.

- [ ] Redeem `NEBIUS-DEVPOST-GLOBAL26`, create a Token Factory key
- [ ] In `.env`: `LLM_PROVIDER=tokenfactory`, `NEBIUS_API_KEY=sk-...`, and
      Token Factory `MODEL_TIER_*` IDs (the defaults already match the catalog)
- [ ] `upgradepilot doctor --json` â†’ exit 0; save under
      `artifacts/submission/nebius/`
- [ ] `pytest -m live` â†’ 4 passed against Token Factory; save the
      `tokenfactory_*` artifacts under `artifacts/submission/nebius/live_calls/`
- [ ] Full offline suite green
- [ ] Demo/video/README/proof card show Token Factory, not
      `integrate.api.nvidia.com`
- [ ] Search the repo for `nvidia-nim` / dev-only claims; no submission artifact
      may present NIM output as Token Factory evidence

## Phases

### Phase 0: Foundations â† CURRENT (NVIDIA dev proof done; Token Factory proof pending)

- [x] Package skeleton `src/upgradepilot/` with pydantic boundaries
- [x] `LICENSE` (MIT, Tushar Kapoor), `.gitignore`, `.env.example`
- [x] Tooling config: `ruff.toml`, `mypy.ini`, `.pre-commit-config.yaml`
- [x] CI: `.github/workflows/ci.yml` (ruff + mypy on src+tests + pytest on
      3.11â€“3.13, coverage gate 70%)
- [x] Catalog parser `catalog.py` on the real snapshot shape (28 models),
      including retrying live fetch
- [x] Tier table built from live catalog prices/context (`tiers.py`)
- [x] LLM client with preflight spending cap + exact post-call accounting
- [x] Tavily client with Bearer auth, 429/5xx retries, plan-limit errors
- [x] CLI: `doctor` (masked keys), `catalog`, `upgrade`/`bench` explicit stubs, `web`
- [x] Web app `GET /healthz`; verified with TestClient and a real uvicorn boot
      (HTTP 200, `artifacts/phase0/web_healthz.txt`)
- [x] Provider abstraction: `LLM_PROVIDER=tokenfactory|nvidia-nim`, separate
      `NEBIUS_API_KEY` / `NVIDIA_API_KEY`, request cap for unpriced NIM
- [x] 62 fast offline tests + 3 subprocess integration tests passing
      (2026-10-21; `pytest` excludes live calls by default)
- [x] NVIDIA NIM dev live calls: 3 tiers + Tavily (`pytest -m live`, 4 passed)
- [x] `doctor` artifact `artifacts/phase0/doctor_no_keys.json` (pass=false
      because keys are missing â€” expected, exit code 1)
- [x] `doctor` NVIDIA dev artifact
      `artifacts/phase0/doctor_nvidia_dev_2026-10-21.json` (pass=true, exit 0)
- [ ] User adds `NEBIUS_API_KEY` to `.env` (Nebius account/key still missing)
- [ ] Run `pytest -m live` against Token Factory â†’ 1 real call per tier + 1
      Tavily search; artifacts land in `artifacts/phase0/live_calls/`
- [ ] Re-run `upgradepilot doctor` with the Nebius key (exit 0)
- [ ] Phase 0 final report after the Token Factory proof

Note: Phase 1a/1b are committed. Phase 2 benchmark work has real verified
cases (see below) and is recorded in `bench/cases.json` (std-lib JSON instead
of YAML â€” no new dependency).

### Phase 1: Harness
- Clone repo at pinned commit, create venv, pinned install, run pytest,
  parse results; unit tests for the parser; demo on one approved repo.
- [x] `harness.py`: `clone_pinned()`, `make_pinned_venv()`, `pip_install()`,
      `run_pytest()` â€” tree-safe timeouts (taskkill /T on Windows, killpg POSIX)
- [x] `verify.py`: `classify_pytest()` â†’ GREEN / STUCK / ENV_FAIL
      (exit-code + ModuleNotFoundError rules; OVERFIT/CHEATED belong to a
      later phase and are never returned here)
- [x] `run_ledger.py`: append-only JSONL run events, UTC timestamps,
      collision-proof run ids
- [x] Ancestor-config isolation: child pytest runs pin their own config file
      (`config_isolation_args`) so a nested workdir cannot inherit our
      pyproject.toml (found and fixed in a real run;
      `tests/test_harness_integration.py::test_run_pytest_ignores_ancestor_config`)
- [x] 121 offline tests passing (fast + subprocess), live calls excluded by default (2026-10-22)
- [x] `verify_with_rollback` checkpoint/rollback wrapper (Phase 3, see below)

### Phase 2: Benchmark cases
Status tracked in `bench/cases.json`; promotion to `verified-passing-to-failing`
happens ONLY after a real `bench/verify_case.py` run (clone â†’ clean venv â†’
pinned install â†’ GREEN pytest â†’ bump ONE dep â†’ failing pytest), with evidence
JSONs under `artifacts/phase2/<case>/`.

- [x] `pytest-lazy-fixture-pytest7-to-8` â€” VERIFIED 2026-10-20:
      MIT, TvoroG/pytest-lazy-fixture @ 18ec85e, pytest 7.4.4 â†’ 8.4.1,
      pre GREEN exit 0, post ENV_FAIL exit 2 (plugin breaks under pytest 8;
      refs TvoroG/pytest-lazy-fixture#65, Debian bug 1066727)
- [x] `pydantic-argparse-pydantic1-to-2` â€” VERIFIED 2026-10-20:
      MIT, SupImDos/pydantic-argparse @ c071998 (0.8.0), pydantic 1.10.22 â†’
      2.12.4, pre GREEN exit 0, post ENV_FAIL exit 4 (v1-only conftest import
      chain breaks under pydantic 2)
- [x] `imodmodel-pytest7-to-8` â€” attempted 2026-10-20, honestly NOT verified:
      baseline under a modern resolution is already broken (35 passed,
      7 setup errors from pytest-lazy-fixture vs numpy 2), so a GREENâ†’broken
      transition cannot be reproduced today. Evidence in
      `artifacts/phase2/imodmodel-pytest7-to-8/`; case stays "candidate".
- Re-attempted 2026-10-27 and still not reproducible, now for a measured
      reason: `pytest-subtests` pinned to tag v0.11.0 (its pre-pytest-8
      release, commit 06315b41) is GREEN → GREEN on pytest 8.4.1
      (`artifacts/phase2/pytest-subtests-pytest7-to-8/run-20261027T111739-bb11fd_green.json`),
      and `pytest-check-links` @ HEAD has a non-GREEN baseline (ENV_FAIL
      exit 2). The load-level screen is now a rerunnable
      script with a saved report: `bench/plugin_load_screen.py` →
      `artifacts/phase2/plugin_load_screen.txt` — 11 pre-pytest-8 releases
      (pytest-asyncio 0.21.1/0.22, pytest-mock 3.11.1, pytest-html 4.1.0,
      pytest-order 1.1.0, pytest-timeout 2.1.0, pytest-sugar 0.9.7,
      pytest-randomly 3.13, pytest-rerunfailures 11.1.2, pytest-xdist 3.3.1,
      pytest-subtests 0.11.0) all collect cleanly under pytest 8.4.1
      (0/11 fail), so a third case needs a source-level breakage, not a
      plugin-load breakage. Case count remains 2.
- [ ] Grow to â‰¥3 verified cases (currently 2). Excluded: python-kasa
      (#491 documents a real pydantic 1â†’2 breakage but is GPL-3 â€” permissive
      licenses only for this repo).

### Phase 3: Guard & held-out checks
- [x] `guard.py`: file hashing, path protection, `CHEATED` status â€” committed
      2026-10-22 (`d8c81b3`); 10 offline tests
- [x] Held-out split (`OVERFIT` detection): `heldout.py` â€” deterministic
      sha256-path split (disjoint, complete, sorted; both sides non-empty
      for â‰¥2 files), `heldout_status()` folds visible+held-out verdicts
- [x] Checkpoint/rollback: `checkpoints.py` `RepoCheckpoint` (byte-level
      snapshot minus venv/git/caches) + `verify_with_rollback` â€” only a
      `GREEN` outcome keeps the tree; anything else restores the snapshot
      and appends a `ROLLED_BACK` ledger event
- [x] 46 new offline tests (`test_heldout.py` 21, `test_checkpoints.py` 6);
      full offline suite green 2026-10-22 (125 collected, 121 + 4 live)
- [x] Phase 4 runs pytest on visible vs held-out subsets and uses
      `heldout_status` at certification

### Phase 4: Agent loop
- triage â†’ research â†’ patch â†’ verify â†’ certify has been implemented and certified end to end:

- [x] `agent.run_upgrade`: triage (cheap tier) → research (Tavily) → patch
      (default tier, escalating on failure) → verify → certify; every step is
      appended to the run ledger with its tier and detail
- [x] Held-out quarantine is physical: held-out test files are moved outside
      the worktree before the patch model sees the repo, and restored at
      certification (`heldout.HeldOutQuarantine`)
- [x] Certification folds guard + rollback: a test-surface edit is `CHEATED`,
      visible-GREEN/held-out-fail is `OVERFIT`, and any non-GREEN outcome
      restores the checkpoint (`guard.guarded_status`,
      `checkpoints.verify_with_rollback`)
- [x] Cost cap wired to the ledger: preflight per-run cap, exact post-call
      accounting, `llm_cost` events per run
- [x] Per-run artifacts: `proof_card.md`, `upgrade_report.json`,
      `test_split.json`, `guard_baseline.json`, `events.jsonl`
- [x] Real recorded run: `artifacts/runs/run-20261023T034032-c06f8b/` — 5
      iterations against `pytest-lazy-fixture` (pytest 7.4.4 → 8.4.1), guard
      clean, verdict `STUCK`: the loop fails honestly rather than editing tests
- [x] Offline coverage: `tests/test_agent.py` (12), `tests/test_guard.py` (17),
      `tests/test_heldout.py` (14), `tests/test_checkpoints.py` (6)

### Demo case: self-written target (not a benchmark)
- [x] `demo/invoicekit`: original MIT invoice calculator pinned to pydantic
      `1.10.22`, 30 visible tests; bump to `2.12.4` breaks the import
      (`PydanticUserError: regex is removed`)
- [x] `demo/heldout/test_heldout_contract.py`: 11 behavioural assertions kept
      outside the work tree and outside every prompt, committed before the first
      agent run (`a654660`)
- [x] Preconditions recorded: `bench/demo_case.py --check` → old pin GREEN
      (30 passed), held-out GREEN (11 passed), bump `ENV_FAIL` exit 4, held-out
      on broken code `ENV_FAIL` (`artifacts/demo/.../preconditions/`)
- [x] Four real rows (`artifacts/demo/demo-invoicekit-pydantic1-to-2/results.md`):
      bump-only `ENV_FAIL`, single-shot `ENV_FAIL` (patch unparseable), agent
      first run `CHEATED` (tried to edit `tests/conftest.py`; rolled back), agent
      after one prompt fix **`GREEN`** — 13 visible passed, external held-out
      contract 11 passed, only `src/invoicekit/models.py` edited
- [x] Provider honesty: every demo row is an NVIDIA NIM dev run (unpriced); the
      demo is never counted in the benchmark and the README says a model may
      have seen this migration before

### Phase 5: Benchmark & baselines
- [x] `bench/verify_case.py` + `bench/cases.json`: 15 cases, 2 verified
      GREEN→broken with raw evidence under `artifacts/phase2/<case>/`
- [x] `bench/results_table.py` + `upgradepilot bench --results`: table built
      only from `artifacts/phase2/<case>/run-*.json`
- [x] `bench/compare.py` (2026-10-27): runs four strategies against the same
      pinned checkout — `bump-only` (control), `codemod` (documented mechanical
      rename table, no model call), `single-shot` (exactly one model patch
      attempt), `agent` (the full Phase 4 loop) — writing
      `artifacts/phase5/<case>/<strategy>/result.json` with each run's pytest
      outcome, guard state, LLM calls/tokens, and wall time, plus the markdown
      table at `artifacts/phase5/results.md`
- [x] 8 real rows recorded across both verified cases. Honest result: **no
      strategy, including the agent, reaches GREEN on either case.**
      `pydantic-argparse` is ENV_FAIL for all four (a v1-only codebase is a
      full migration, not a repair), and `pytest-lazy-fixture` goes
      ENV_FAIL → STUCK (single-shot) / CHEATED (agent)
- Finding 2026-10-27 (fixed 2026-10-28): on `pytest-lazy-fixture` the agent was
      labelled `CHEATED` because the patched run reported 1 newly skipped and 1
      newly xfailed test *against a baseline that never collected*. That was D1.
      The guard now compares skip/xfail counts against the **old-pin GREEN run**
      recorded before the bump; the reference is passed by `prepare_target`
      (`verify_old_pin`) and by every `bench/compare.py` / `bench/demo_case.py`
      row. Original evidence:
      `artifacts/phase5/pytest-lazy-fixture-pytest7-to-8/agent/pytest-lazy-fixture-pytest7-to-8--agent/attempts/attempt_01_guard_violation.json`
- [x] D1/D2/D4 fixed and pinned by tests (commit `a654660`):
      `tests/test_guard.py` (skip reference), `tests/test_agent_regressions.py`
      (no false CHEATED on a repaired suite; new skip still CHEATED; real
      rollback reason; provider/models/versions in the report),
      `tests/test_prepare.py` + `tests/test_harness_integration.py` (old-pin
      install order and resolved versions)
- [x] Phase 5 re-run with the fixes (`artifacts/phase5/results.md`, 2026-10-28):
      8 rows again, each now recording provider, model IDs, `run_class` and
      resolved Python/pytest/package versions. `pytest-lazy-fixture` agent went
      `CHEATED` → `STUCK` (12 passed, 33 failed); pydantic-argparse stays
      `ENV_FAIL` ×4. **0 of 8 rows reach GREEN.** Addendum in
      `artifacts/phase5/REPORT.md`
- [x] Write-up: `artifacts/phase5/REPORT.md` (method, environment,
      provenance, all 8 rows, the guard and rollback defects found, and what it
      means for the submission)
- [ ] The case set still lacks a case this loop can solve. Until one exists
      there is no GREEN run to show, and the demo must not imply otherwise.

### Phase 6: CLI polish & web app
- [x] SSE live runs, proof cards, benchmark table, accessible UI, as follows:
- [x] `web/app.py` factory + `web/runs.py` controller: `GET /` (UI),
      `GET /healthz` (Phase 0 contract kept), `GET /api/runs`,
      `GET /api/runs/{id}`, `GET /api/runs/{id}/events` (SSE replay then live
      tail), `GET /api/bench`, `POST /api/runs` (409 while a run is active)
- [x] No Node build step: static `index.html` / `styles.css` / `app.js` served
      from `web/static/`, with skip link, labeled fields, live regions, and
      keyboard-focusable, labeled tables
- [x] Test coverage: `tests/test_web_app.py` (16) + `tests/test_web_healthz.py`
      cover the page, every JSON endpoint, exact SSE framing, and the busy 409
- [x] Live check 2026-10-27: real uvicorn boot on 127.0.0.1:8017 — `/healthz`
      `{"status":"ok"}`, runs table showing the recorded run, bench table from
      real artifacts, SSE replay of a recorded run's events, accessible alert
      on an empty form; no console errors

### Phase 7: Submission assets
- [x] Recorded-runs site (`src/upgradepilot/site.py`, `upgradepilot site
      build`): 13 run pages, comparison page keeping benchmark and demo apart,
      semantic HTML, keyboard/AA/light-dark/phone-width, empty + unreadable
      artifact states, `docs/.nojekyll` (2026-10-28)
- [x] `docs/adding-a-benchmark-case.md` and `FEEDBACK.md` (feedback split into
      repository-proven facts vs. author-reported setup friction)
- [x] README completion: provider-honesty statement (no Token Factory call),
      demo-case section, site section, Related Work limited to sources actually
      read, limitations; verification table current (2026-10-28)
- [x] ARCHITECTURE completion: run pipeline, guard/held-out invariants,
      cost model, artifacts, web layer, testing strategy
- [x] Devpost text (`DEVPOST.md`) and demo shot list (`VIDEO.md`)
- [x] Fresh-clone verification (2026-10-27): clone under a different
      directory name → `pip install -e ".[web,dev]"` → `ruff check .`,
      `ruff format --check .`, `mypy src tests`, `pytest tests` all green
      (175 passed). Caught and fixed one real portability bug:
      `test_repo_root_is_beside_tests` had hard-coded the checkout name.
- [x] Fresh-clone re-verification (2026-10-28, commit 823ccc1): fresh clone in
      a new directory → `pip install -e ".[web,dev]"` → `cp .env.example .env`
      → `doctor` (keys FAIL as documented, catalog/tiers OK) → `pytest tests`
      194 passed, 4 deselected; `ruff check .`, `ruff format --check .`,
      `mypy src tests` all clean in the clone too.
- [ ] Video recording and public YouTube upload (manual, under 3 minutes; `VIDEO.md` is the script)
- [ ] Publish the cleaned repository to `https://github.com/Tusharkapoor-oop/Nividia-X-Nebius-` after the secret scan (the target currently reports empty)
- [ ] Deploy `docs/` with GitHub Pages and verify the public URL; describe it as a recorded-run showcase, not a live service
- [ ] Select the **Coding and Agentic Engineering** track on the Devpost form
- [ ] Run live Token Factory doctor/probes after `NEBIUS_API_KEY` is configured; do not relabel NVIDIA NIM artifacts as Token Factory

