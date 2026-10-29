# UpgradePilot

> A trustworthy dependency-upgrade agent for Python projects.

UpgradePilot upgrades **one** Python dependency per run, then proves the result
instead of asserting it: it records the target's suite before the bump, keeps a
held-out check set out of the patching context, guards test files against edits,
and emits a proof card with the commands, diffs, and verification results.

Built for the **Nebius x NVIDIA Global AI Hackathon** (Coding and Agentic
Engineering track).

## Provider status — read this first

**No Nebius Token Factory call has been made from this repository.** The
`.env` in this build has an empty `NEBIUS_API_KEY`, so every model call recorded
in `artifacts/` is an **NVIDIA NIM development run** (`integrate.api.nvidia.com`)
using Nemotron. NIM is a development provider: it is not submission-eligible and
publishes no price catalog, so those calls are recorded as *unpriced* with no
invented dollar figure. Every result file states `provider`, the model IDs, a
`run_class` of `dev` or `submission`, and the resolved Python/pytest/package
versions. Nothing in this repository labels a dev run as Token Factory.

## Status (verified 2026-10-29)

| Check | Result | Evidence |
|-------|--------|----------|
| Offline test suite | **195 passed, 4 live tests deselected** | `pytest tests` |
| Lint / format / types | `ruff check src tests bench`, `ruff format --check src tests bench`, `mypy src tests` clean | application/test/benchmark paths pass; scratch scripts at the repo root are excluded |
| Demo case, full loop | **GREEN** — 13 visible + 11 external held-out assertions | `artifacts/demo/demo-invoicekit-pydantic1-to-2/agent/result.json` |
| Demo case, before that | **CHEATED** (patch tried to edit `tests/conftest.py`; rolled back) | `.../agent-run1/result.json` |
| Demo baselines | bump-only `ENV_FAIL`, single-shot `ENV_FAIL` (no usable patch) | `.../{bump-only,single-shot}/result.json` |
| CLI end-to-end | `upgradepilot upgrade demo/invoicekit ...` → **GREEN**, 3 iterations, internal held-out GREEN | `artifacts/runs/run-20261028T041417-69228f/` |
| Strategy comparison (Phase 5) | 8 real rows across 2 benchmark cases; **no strategy reaches GREEN** | `artifacts/phase5/results.md` |
| Benchmark cases | 2 verified GREEN→failing out of 15 candidates | `artifacts/phase2/` |
| Token Factory call | **none — no key available** | `upgradepilot doctor` fails the `keys` check |
| Recorded-runs site | 14 run pages generated from artifact JSON | `docs/index.html` |
| Fresh-clone quickstart | verified twice in a differently-named checkout (2026-10-27 and 2026-10-28: 194 passed, gates clean); current checkout: 195 passed in the submission snapshot | `PLAN.md` Phase 7 |
| GitHub repository | [submission target](https://github.com/Tusharkapoor-oop/Nividia-X-Nebius-) | currently empty; publish is pending |
| Hosted demo URL | `docs/` contains the static recorded-runs site | GitHub Pages is not deployed; no live public URL verified |

Every number above comes from a file under `artifacts/`; nothing is estimated.

## The demo case (self-written — not a benchmark)

`demo/invoicekit` is an original MIT invoice calculator pinned to
pydantic `1.10.22`. Its suite is GREEN on the old pin and fails to **import**
after the bump to `2.12.4` (`PydanticUserError: regex is removed`). An external
held-out contract of 11 behavioural assertions lives in `demo/heldout/`, was
committed **before** the first agent run, and is never copied into the agent's
work tree.

| Strategy | Provider | Status | Visible suite | Held-out contract |
|----------|----------|--------|---------------|-------------------|
| bump-only | NVIDIA NIM (dev run) | `ENV_FAIL` | 0 passed | `ENV_FAIL` |
| single-shot | NVIDIA NIM (dev run) | `ENV_FAIL` | 0 passed (patch unparseable) | `ENV_FAIL` |
| agent, first run | NVIDIA NIM (dev run) | `CHEATED` | 0 passed | `ENV_FAIL` |
| agent, after one prompt fix | NVIDIA NIM (dev run) | **`GREEN`** | 13 passed, 0 failed | **11 passed, 0 failed** |

The first agent run is kept on purpose: the model tried to edit
`tests/conftest.py`, the guard rejected the patch, and the run ended `CHEATED`
instead of passing. The second run migrated `src/invoicekit/models.py` only
(`@validator`/`@root_validator` → `field_validator`/`model_validator`,
`regex` → `pattern`, `Config` → `ConfigDict`, `parse_obj` → `model_validate`)
and certified GREEN.

Reproduce it:

```bash
python bench/demo_case.py --check        # old pin GREEN, bump fails, held-out fails
python bench/demo_case.py                # bump-only, single-shot, agent + held-out certification
python bench/demo_case.py --table-only   # regenerate artifacts/demo/.../results.md
```

**What this proves and what it does not.** A model may already have seen pydantic
v1 → v2 migrations, so a GREEN demo shows the pipeline works end to end; it is
not evidence of generalisation to unseen repositories. The two third-party
benchmark cases below show that limit directly.

## Benchmark (Phase 5): the honest negative result

`bench/compare.py` runs four strategies on the *same* pinned checkout per case —
`bump-only` (control), `codemod` (documented mechanical renames, no model call),
`single-shot` (one patch attempt), and `agent` (the full loop). Eight real rows
across two verified cases:

- `pydantic-argparse` (pydantic 1.10.22 → 2.12.4): old pin is GREEN with 746
  passing tests; after the bump all four strategies end `ENV_FAIL` — a v1-only
  codebase is a migration, not a repair.
- `pytest-lazy-fixture` (pytest 7.4.4 → 8.4.1): old pin GREEN (45 passed, 1
  skipped, 1 xfailed); after the bump the plugin cannot load. The agent repairs
  collection and reaches `STUCK` with 12 passed / 33 failed in 5 iterations; the
  other strategies stay at `ENV_FAIL` / `STUCK`.

**No strategy reaches GREEN on either case.** That is the result; the table is
in `artifacts/phase5/results.md` (each row now records provider, models, and
resolved versions). The analysis, including the defects this comparison exposed
(D1–D6), is in `artifacts/phase5/REPORT.md`, with an addendum covering the
post-fix re-run.

## Requirements

- Python 3.11+ (developed on 3.13.15, Windows)
- git
- API keys: `NVIDIA_API_KEY` (development) or `NEBIUS_API_KEY` (submission),
  plus `TAVILY_API_KEY`
- `LLM_PROVIDER=tokenfactory|nvidia-nim` (default `tokenfactory`)

## Setup (clean Windows machine)

```powershell
git clone https://github.com/Tusharkapoor-oop/Nividia-X-Nebius-.git upgradepilot
cd upgradepilot
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[web,dev]"
Copy-Item .env.example .env
# edit .env:
#   submission:  LLM_PROVIDER=tokenfactory  NEBIUS_API_KEY=sk-...
#   development: LLM_PROVIDER=nvidia-nim    NVIDIA_API_KEY=nvapi-...
# both need TAVILY_API_KEY
.\.venv\Scripts\upgradepilot.exe doctor
```

`.env` is git-ignored and `doctor` prints only masked key prefixes. `doctor`
without keys is expected to fail the `keys` check; the catalog and tier checks
still run, so setup can be validated before keys exist.

## CLI

```powershell
upgradepilot doctor                     # environment, keys, catalog, tiers, live probes
upgradepilot doctor --json              # machine-readable; exit 1 if any check fails
upgradepilot catalog                    # live catalog + configured tiers
upgradepilot upgrade <repo> --package <name> --to <version>
                                        # disposable checkout, old-pin reference,
                                        # bump, repair loop, proof card
upgradepilot bench --list               # benchmark cases
upgradepilot bench --results            # table from artifacts/phase2 JSON only
upgradepilot site build                 # static recorded-runs site into docs/
upgradepilot web                        # local FastAPI app (SSE live runs)
```

`upgrade` runs the real pipeline: it copies the target, builds a venv, installs
the project's own pins, runs the suite on the old pin as the masking reference,
installs the requested version, records resolved versions, then runs the agent
loop. Exit code is 0 only for `GREEN`.

## Recorded-runs site

`upgradepilot site build` renders `docs/` from artifact JSON files only: one page
per recorded run (timeline, proof card, provider, environment, raw JSON), a
comparison page that keeps benchmark and demo rows apart, and an about page. The
HTML is semantic, keyboard navigable with visible focus, AA-contrast in light
and dark mode, responsive to phone width, and shows explicit empty and
unreadable-artifact states. There is no JavaScript and no build step.

The hosted copy shows **recorded runs**, not a live service. To run the pipeline
yourself, follow Setup above and run `upgradepilot upgrade ...` locally.

GitHub Pages: point Pages at the `docs/` folder on the default branch
(`docs/.nojekyll` is generated for you). The pages are labelled **Recorded run**
and show NVIDIA NIM as development-only; the GREEN NIM demo is not a live
Token Factory demo.

## How the guard works

1. Every test file, `conftest.py`, and pytest config is hashed before the model
   sees the repository (`guard_baseline.json`).
2. After each patch, the surface is re-hashed. Any modification, addition, or
   deletion is a violation: the checkpoint is restored and the run ends
   `CHEATED`.
3. Newly skipped or xfailed tests are also a violation — measured against the
   **old-pin GREEN run** recorded before the bump, never against a post-bump run
   that failed to collect. (This was defect D1 in the Phase 5 report; the fix is
   pinned by `tests/test_agent_regressions.py` and `tests/test_guard.py`.)
4. Files or packages that would shadow the upgraded dependency are rejected.

## How held-out certification works

Test modules are split deterministically by `sha256(path)` into visible and
held-out sets. Held-out files are moved **outside** the worktree while the model
patches, then restored for certification. Visible GREEN + held-out GREEN
certifies `GREEN`; visible GREEN + held-out failing is `OVERFIT`. The demo case
adds a second, stronger check: an external contract that was never in the
checkout at all.

## Model tiers

Token Factory prices and context limits are read from the live catalog on every
run; only the model choice is configuration, and a run fails closed if the
configured model is absent, inactive, or unpriced.

| Role | Token Factory model (submission) | NIM model (development, unpriced) |
|------|----------------------------------|-----------------------------------|
| cheap / triage | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | `nvidia/nemotron-3.5-lightning-30b-a3b` |
| default / patch | `nvidia/Nemotron-3_5-Lightning` | `nvidia/nemotron-3.5-lightning-30b-a3b` |
| strong / escalate | `nvidia/Nemotron-3-Ultra-550b-a55b` | `nvidia/nemotron-3-ultra-550b-a55b` |

Token Factory per-million prices for the three tiers are verified against the
2026-10-20 catalog snapshot in `PLAN.md`. NIM has no pricing catalog, so NIM
runs are capped by `MAX_LLM_CALLS_PER_RUN` and recorded as unpriced.

## Repository layout

```text
src/upgradepilot/
  agent.py       the loop: reference → quarantine → baseline → triage → research
                 → patch → guard → verify → certify; proof cards
  guard.py       test-surface hashing, CHEATED verdicts, skip/xfail masking check
  heldout.py     deterministic split, physical quarantine, OVERFIT verdicts
  checkpoints.py byte-level snapshot/restore used for rollback
  harness.py     clone/venv/pinned installs, pytest runner, resolved versions
  prepare.py     disposable checkout, old-pin-first install, setup.json
  verify.py      pytest → GREEN / STUCK / ENV_FAIL
  editing.py     apply model patches (source files only)
  llm.py         chat client, retries, per-run cap, exact accounting
  catalog.py     live Token Factory catalog
  tiers.py       tier policy (prices from the catalog only)
  research.py    Tavily client
  site.py        static recorded-runs site generator
  cli.py         doctor / catalog / upgrade / bench / site / web
  web/           FastAPI app: SSE live runs, proof cards, benchmark table
bench/
  cases.json            benchmark candidates and their verification status
  verify_case.py        prove one case GREEN → broken and record it
  compare.py            four strategies on the same checkout + markdown table
  demo_case.py          the self-written demo case and its held-out contract
  results_table.py      benchmark table from raw phase-2 artifacts
demo/
  invoicekit/           demo target (pydantic 1.10.22, 30 visible tests)
  heldout/              11 external assertions, committed before the first run
docs/                   generated recorded-runs site (GitHub Pages)
artifacts/              raw evidence: runs, phase0, phase2, phase5, demo
```

## Development

```powershell
.\.venv\Scripts\python.exe -m pytest tests
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy src tests
```

Live tests make real billable calls and are opt-in (`pytest -m live`); they
self-skip when the active key is absent. Offline tests are isolated from the
developer's `.env` by `tests/conftest.py`, so switching providers cannot change
their results.

## Limitations

- **No Token Factory run exists.** The submission path is implemented and
  configured, but without a Nebius key it has never been exercised end to end.
  Every GREEN claim here is a development run on NVIDIA NIM.
- **The demo case is self-written.** It shows the pipeline works; it does not
  show generalisation. Both third-party benchmark cases remain `ENV_FAIL`
  because they are full migrations rather than repair-sized breakages.
- **Held-out certification is only a mask check on real repos.** With a single
  test file there is nothing to hold out internally; the demo case solves this
  with an external contract, but third-party cases do not have one.
- **Windows-first.** Subprocess tree-kill and venv paths are implemented for
  POSIX too, but the recorded runs were produced on Windows.
- **Unpriced provider.** NIM runs report tokens and call counts only; no USD
  figure is claimed.

## Related work (sources actually read while building this)

- **Pydantic V2 migration guide** (<https://docs.pydantic.dev/latest/migration/>):
  the source for the rename table used by this project's `codemod` baseline
  (`parse_obj` → `model_validate`, `dict` → `model_dump`, `__fields__` →
  `model_fields`, and others) and for the demo case's required migration. It also
  documents the authors' own `bump-pydantic` transformation tool, which is the
  closest existing prior art to what the `codemod` strategy does here.
- **pytest changelog** (<https://docs.pytest.org/en/stable/changelog.html>): the
  breaking-change and deprecation policy quoted when explaining why the
  `pytest-lazy-fixture` and `pytest-subtests` cases behave as they do, including
  pytest 9.2.0's rule that a failing `conftest.py` import is a usage error
  (exit 4) rather than a plain test failure.

No other tool is described here, because no other source was read.

## License

MIT — see `LICENSE`. The demo target (`demo/invoicekit`) is original code by the
same author under the same license; benchmark repositories keep their own
licenses and are only cloned at pinned commits, never vendored.
