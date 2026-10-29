# Adding a benchmark case

A benchmark case is a real, third-party, permissively licensed repository that
passes its own tests at one pinned dependency version and fails at the next.
Nothing is a "case" until a recorded run proves that transition.

## 1. Pick the repository

- Permissive license only (MIT / Apache-2.0 / BSD). The set excludes GPL
  projects such as `python-kasa` for that reason.
- Small enough to install in a fresh venv within a couple of minutes.
- The dependency bump must be **one** package, and the failure must come from
  source-level code, not from a plugin that pytest still loads. The plugin-load
  screen (`bench/plugin_load_screen.py`) shows that pre-pytest-8 releases such
  as `pytest-asyncio 0.21.1` still import under pytest 8.4.1, so a case built
  only on "old plugin no longer loads" will not reproduce today.
- The repository needs test files the guard can hash and, ideally, at least
  two test modules so the held-out split is internal.

## 2. Record it in `bench/cases.json`

```json
{
  "id": "example-pytest7-to-8",
  "status": "candidate",
  "source": "https://github.com/owner/repo",
  "commit": "<full sha of the pinned checkout>",
  "license": "MIT",
  "dep": "pytest",
  "old_pin": "pytest==7.4.4",
  "new_pin": "pytest==8.4.1",
  "notes": "why this bump is expected to break",
  "pre_install_pins": []
}
```

`status` starts as `candidate`. It becomes `verified-passing-to-failing` only
after step 3 records real evidence; anything else stays a candidate, including
cases that turned out not to reproduce.

## 3. Prove the transition

```bash
python bench/verify_case.py --case example-pytest7-to-8
```

That clones at the pinned commit, builds a clean venv, installs the old pin,
runs the suite (must be GREEN), installs the new pin, runs again (must not be
GREEN), and writes both raw outcomes under `artifacts/phase2/<case>/`. The
command fails if either expectation is not met. Promote the case in
`bench/cases.json` only with those files present.

## 4. Compare strategies (optional, Phase 5)

```bash
python bench/compare.py --case example-pytest7-to-8
```

runs `bump-only`, `codemod`, `single-shot` and `agent` on the same pinned
checkout. Each row records the old-pin reference run (the masking reference for
the guard), the post-bump baseline, the final outcome, provider, model IDs,
resolved Python/pytest/package versions, tokens, and wall time under
`artifacts/phase5/<case>/<strategy>/result.json`. `python bench/compare.py
--table-only` regenerates `artifacts/phase5/results.md` from those files.

## 5. Demos are not cases

`demo/invoicekit` is a self-written target used to show the pipeline end to end
(`bench/demo_case.py`). It never enters `bench/cases.json`, never appears in the
benchmark table, and its results live under `artifacts/demo/`. A model may have
seen a pydantic v1 → v2 migration before, so a GREEN demo run shows that the
pipeline works, not that the agent generalises.
