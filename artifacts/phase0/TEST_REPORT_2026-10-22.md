# UpgradePilot — Test Report

- **Date:** 2026-10-22
- **Project:** UpgradePilot v0.1.0 — trustworthy dependency-upgrade agent for Python
- **Environment:** Windows NT 10.0.26300 · PowerShell 5.1 · Python 3.13.15 · pytest 9.1.1 · git 2.55.0
- **Provider under test:** `LLM_PROVIDER=nvidia-nim` (development; submission requires Nebius Token Factory)
- **Repo**: `c:\Users\ACER\Downloads\Nividia X nebius\upgradepilot` (HEAD `c5d7a0c`, working tree has uncommitted Phase-3 guard files)

---

## 1. Executive summary

**Result: ALL 79 TESTS PASS (**`75` offline + `4` live**). Quality gates and `doctor` health checks also clean.**

| Suite / gate | Collected | Passed | Failed | Deselected | Result | Time |
|---|---|---|---|---|---|---|
| Offline suite — `pytest tests` (`-m 'not live'`) | 79 | **75** | **0** | 4 (live) | ✅ exit 0 | 107.44 s |
| Live suite — `pytest -m live` | 4 | **4** | **0** | 75 (offline) | ✅ exit 0 | 18.49 s |
| **Total** | **79** | **79** | **0** | — | ✅ | — |
| `ruff check .` | — | ✅ | — | — | exit 0 | — |
| `ruff format --check .` | 44 files | ✅ | — | — | exit 0 | — |
| `mypy src tests` | 35 files | ✅ | — | — | exit 0 | — |
| `doctor` (NVIDIA NIM dev) | 7 checks | 7 | 0 | — | ✅ exit 0 | — |
| `doctor` (Token Factory config) | 8 checks | 7 | 1* | — | ⚠️ exit 1 (expected) | — |

> \* The single non-passing `doctor` check is `keys`: `NEBIUS_API_KEY=<unset>`. The Token Factory catalog,
> tier pricing, and Tavily all pass; the live chat probe honestly reports `skipped (no key)`. This is the
> known submission blocker and is expected until a Nebius key is added and `LLM_PROVIDER` is flipped.

**Warnings:** 1 benign `StarletteDeprecationWarning` (FastAPI `testclient` ↔ `httpx` integration, no action needed).

---

## 2. Offline test suite — per-test results

Command: `python -m pytest tests -o addopts='' -m 'not live' -v --tb=short --durations=10`

Result: **75 passed, 4 deselected, 1 warning in 107.44 s (0:01:47)** — **exit 0**.

### 2.1 Per-file overview

| Test file | Tests | Passed | Failed |
|---|---|---|---|
| tests/test_catalog.py | 11 | 11 | 0 |
| tests/test_cli.py | 3 | 3 | 0 |
| tests/test_config.py | 6 | 6 | 0 |
| tests/test_doctor.py | 2 | 2 | 0 |
| tests/test_guard.py | 10 | 10 | 0 |
| tests/test_harness_integration.py | 3 | 3 | 0 |
| tests/test_harness_parser.py | 5 | 5 | 0 |
| tests/test_llm.py | 8 | 8 | 0 |
| tests/test_models.py | 2 | 2 | 0 |
| tests/test_provider_modes.py | 8 | 8 | 0 |
| tests/test_research.py | 4 | 4 | 0 |
| tests/test_retry.py | 3 | 3 | 0 |
| tests/test_secrets.py | 4 | 4 | 0 |
| tests/test_verify.py | 5 | 5 | 0 |
| tests/test_web_healthz.py | 1 | 1 | 0 |
| **Total** | **75** | **75** | **0** |

### 2.2 Full per-test status — all 75 ✅ PASSED

**tests/test_catalog.py (11/11 ✅)**
- `test_parse_counts_nvidia_models` — PASSED
- `test_tier_model_ids_resolve` — PASSED
- `test_tier_pricing_and_context_from_catalog` — PASSED
- `test_config_defaults_match_verified_tiers` — PASSED
- `test_build_tiers_uses_live_catalog_prices` — PASSED
- `test_missing_model_id_raises` — PASSED
- `test_fetch_catalog_retries_then_parses` — PASSED
- `test_fetch_catalog_exhaustion_is_typed` — PASSED
- `test_parse_catalog_rejects_non_array` — PASSED
- `test_parse_catalog_all_entries_broken_raises` — PASSED
- `test_default_flavor_prefers_largest_context` — PASSED

**tests/test_cli.py (3/3 ✅)**
- `test_upgrade_requires_named_package_and_to_options` — PASSED
- `test_upgrade_stub_reports_not_wired` — PASSED
- `test_bench_stub_reports_not_wired` — PASSED

**tests/test_config.py (6/6 ✅)**
- `test_settings_without_keys_key_state` — PASSED
- `test_settings_keys_stripped` — PASSED
- `test_require_keys_names_every_missing_key` — PASSED
- `test_nim_mode_requires_nvidia_key_not_nebius` — PASSED
- `test_active_key_follows_provider` — PASSED
- `test_repo_root_is_beside_tests` — PASSED

**tests/test_doctor.py (2/2 ✅)**
- `test_doctor_checks_offline_structure` — PASSED
- `test_doctor_reports_catalog_failure` — PASSED

**tests/test_guard.py (10/10 ✅) — Phase 3 guard (CHEATED detection)**
- `test_snapshot_covers_names_conftest_and_config` — PASSED
- `test_snapshot_ignores_venv_git_cache` — PASSED
- `test_weakened_assertion_is_flagged_as_modified` — PASSED
- `test_deleted_test_file_is_flagged` — PASSED
- `test_added_test_file_is_flagged` — PASSED
- `test_conftest_and_pytestini_edits_are_flagged` — PASSED
- `test_source_patch_alone_is_not_flagged` — PASSED
- `test_snapshot_json_roundtrip` — PASSED
- `test_guarded_status_folds_guard_evidence_over_pytest` — PASSED
- `test_report_summary_text` — PASSED

**tests/test_harness_integration.py (3/3 ✅) — real git/venv/pip/pytest subprocesses**
- `test_clone_venv_pytest_end_to_end` — PASSED (28.29 s)
- `test_run_pytest_timeout_kills_tree` — PASSED (40.83 s)
- `test_run_pytest_ignores_ancestor_config` — PASSED (29.72 s)

**tests/test_harness_parser.py (5/5 ✅)**
- `test_parse_basic_pass` — PASSED
- `test_parse_mixed_counts` — PASSED
- `test_parse_warnings_and_xfailing` — PASSED
- `test_no_summary_is_not_fabricated` — PASSED
- `test_collect_errors_are_errors` — PASSED

**tests/test_llm.py (8/8 ✅)**
- `test_call_cost_math` — PASSED
- `test_estimate_prompt_tokens_is_conservative` — PASSED
- `test_preflight_cap_blocks_call` — PASSED
- `test_cap_blocks_followup_after_booking` — PASSED
- `test_429_then_success_with_retry` — PASSED
- `test_401_is_non_retryable` — PASSED
- `test_empty_choices_is_an_error` — PASSED
- `test_default_max_tokens_comes_from_tier` — PASSED

**tests/test_models.py (2/2 ✅)**
- `test_cost_record_tracks_tokens_and_cost` — PASSED
- `test_llm_response_defaults` — PASSED

**tests/test_provider_modes.py (8/8 ✅) — NVIDIA NIM / Token Factory provider honesty**
- `test_nim_tiers_have_no_prices` — PASSED
- `test_call_cost_refuses_unpriced_tier` — PASSED
- `test_request_cap_blocks_before_network` — PASSED
- `test_nim_uses_nvidia_key_and_endpoint` — PASSED
- `test_tokenfactory_payload_has_no_nim_thinking_flag` — PASSED
- `test_unpriced_calls_are_not_dollarized` — PASSED
- `test_nim_never_dollarizes_even_with_a_priced_tier` — PASSED
- `test_tokenfactory_mode_still_usd_caps` — PASSED

**tests/test_research.py (4/4 ✅)**
- `test_search_uses_bearer_header` — PASSED
- `test_429_retries_and_succeeds` — PASSED
- `test_plan_limit_432_clear_error` — PASSED
- `test_401_clear_error_no_retry` — PASSED

**tests/test_retry.py (3/3 ✅)**
- `test_gives_up_after_max_attempts` — PASSED
- `test_success_after_failures` — PASSED
- `test_retry_after_header_is_honoured` — PASSED

**tests/test_secrets.py (4/4 ✅)**
- `test_mask_never_returns_the_tail` — PASSED
- `test_mask_empty_and_short_values` — PASSED
- `test_redact_known_key_shapes` — PASSED
- `test_redact_leaves_ordinary_words_alone` — PASSED

**tests/test_verify.py (5/5 ✅)**
- `test_green_when_exit_zero` — PASSED
- `test_stuck_on_plain_failures` — PASSED
- `test_env_fail_on_collector_and_usage_and_no_tests` — PASSED
- `test_env_fail_on_missing_dependency` — PASSED
- `test_run_ledger_roundtrip` — PASSED

**tests/test_web_healthz.py (1/1 ✅)**
- `test_healthz` — PASSED

### 2.3 Slowest tests (from `--durations=10`)

| Duration | Test |
|---|---|
| 40.83 s (call) | tests/test_harness_integration.py::test_run_pytest_timeout_kills_tree |
| 29.72 s (call) | tests/test_harness_integration.py::test_run_pytest_ignores_ancestor_config |
| 28.29 s (call) | tests/test_harness_integration.py::test_clone_venv_pytest_end_to_end |
| 1.85 s (call) | tests/test_research.py::test_429_retries_and_succeeds |
| 1.15 s (call) | tests/test_web_healthz.py::test_healthz |
| 0.61 s (call) | tests/test_llm.py::test_429_then_success_with_retry |

The three subprocess tests dominate the runtime by design (they create real venvs, clone pinned repos, pip instal, and run real pytest).

### 2.4 Warnings (1, benign)

```
tests/test_web_healthz.py::test_healthz
  StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is
  deprecated; install `httpx2` instead. (from fastapi/testclient.py)
```
No action required — upstream library deprecation notice, does not affect results.

---

## 3. Live test suite (NVIDIA NIM dev provider) — per-test results

Command: `python -m pytest -o addopts='' -m live -v --tb=short`

Result: **4 passed, 75 deselected in 18.49 s** — **exit 0**. Real network calls: 3 model-tier chat probes via
NVIDIA NIM (`integrate.api.nvidia.com`) + 1 Tavily search.

| Test | Result | Evidence artifact |
|---|---|---|
| `tests/test_live_calls.py::test_live_llm_call_per_tier[cheap]` | ✅ PASSED | artifacts/phase0/live_calls/nvidia_nim_cheap.json |
| `tests/test_live_calls.py::test_live_llm_call_per_tier[default]` | ✅ PASSED | artifacts/phase0/live_calls/nvidia_nim_default.json |
| `tests/test_live_calls.py::test_live_llm_call_per_tier[strong]` | ✅ PASSED | artifacts/phase0/live_calls/nvidia_nim_strong.json |
| `tests/test_live_calls.py::test_live_tavily_search` | ✅ PASSED | artifacts/phase0/live_calls/tavily_search.json |

Also written: `artifacts/phase0/live_calls/catalog_summary.json` (tier/cap summary for the run).

Each tier probe asserts the model returned the probe token (`OK`), `finish_reason=stop`, and non-zero token
usage. NIM calls are recorded as **unpriced** (`cost_usd=null`, `unpriced_calls=1`) — no dollar figure is
ever invented for a provider without a pricing catalog (verified by the offline `test_provider_modes.py`).

---

## 4. Quality gates

Command: `python -m ruff check .` (then `ruff format --check .`, then `mypy src tests`)
Log: `artifacts/phase0/test_log_gates_2026-10-22.txt`

| Gate | Output (abridged) | Exit |
|---|---|---|
| `ruff check .` | `All checks passed!` | 0 ✅ |
| `ruff format --check .` | `44 files already formatted` | 0 ✅ |
| `mypy src tests` | `Success: no issues found in 35 source files` | 0 ✅ |

---

## 5. `doctor` health checks

### 5.1 NVIDIA NIM (development provider) — `upgradepilot doctor --json`
Evidence: `artifacts/phase0/doctor_nvidia_dev_2026-10-22.json` — **`"pass": true`, exit 0**

| Check | OK | Detail |
|---|---|---|
| python>=3.11 | ✅ | 3.13.15 |
| git | ✅ | git version 2.55.0.windows.5 |
| keys | ✅ | provider=nvidia-nim `NVIDIA_API_KEY=nvap...` `TAVILY=tvly...` |
| hackathon mode | ✅ | DEV (nvidia-nim) — notes submission requires tokenfactory |
| tier mapping | ✅ | cheap/default: nemotron-3.5-lightning-30b-a3b; strong: nemotron-3-ultra-550b-a55b — unpriced, cap=requests/12 |
| llm chat | ✅ | nemotron-3.5-lightning-30b-a3b in=21 out=2 finish='stop' content='OK' (unpriced) |
| tavily search | ✅ | 1 result(s), credits=1 |

### 5.2 Token Factory (submission config, no Nebius key yet) — `upgradepilot doctor --json`
Evidence: `artifacts/phase0/doctor_tokenfactory_2026-10-22.json` — **`"pass": false`, exit 1 (expected)**

| Check | OK | Detail |
|---|---|---|
| python>=3.11 / git | ✅ | 3.13.15 / git 2.55.0.windows.5 |
| keys | ❌ | provider=tokenfactory `NEBIUS_API_KEY=<unset>` (Tavily OK) |
| hackathon mode | ✅ | SUBMISSION PATH (tokenfactory) |
| tokenfactory catalog | ✅ | 28 models listed (live fetch) |
| tier mapping | ✅ | Nano $0.06/$0.24 ctx=262144 · Lightning $0.06/$0.24 ctx=1048576 · Ultra $1.00/$3.00 ctx=1048576 |
| tokenfactory chat | ✅* | *skipped (no key)* — honest skip, not a false pass |
| tavily search | ✅ | 1 result(s), credits=1 |

> The single failure is the missing `NEBIUS_API_KEY`. This is the documented submission blocker.
> All Token Factory wiring (catalog, tier pricing, model IDs) is verified working.

---

## 6. Log & evidence files produced (2026-10-22)

| File | Contents |
|---|---|
| `artifacts/phase0/TEST_REPORT_2026-10-22.md` | This report |
| `artifacts/phase0/test_log_offline_2026-10-22.txt` | Full verbose offline run (79 collected, 75 selected, per-test PASSED lines, warnings, durations, summary) |
| `artifacts/phase0/test_log_live_2026-10-22.txt` | Full verbose live run (4 PASSED lines + summary) |
| `artifacts/phase0/test_log_gates_2026-10-22.txt` | ruff check / ruff format --check / mypy outputs + exit codes |
| `artifacts/phase0/doctor_nvidia_dev_2026-10-22.json` | doctor JSON, NVIDIA NIM dev — pass=true |
| `artifacts/phase0/doctor_tokenfactory_2026-10-22.json` | doctor JSON, Token Factory config — pass=false (key missing) |
| `artifacts/phase0/live_calls/nvidia_nim_{cheap,default,strong}.json` | Raw live chat-call evidence |
| `artifacts/phase0/live_calls/tavily_search.json` | Raw Tavily search evidence |
| `artifacts/phase0/live_calls/catalog_summary.json` | Tier/cap summary of the live run |

---

## 7. Notes & observations

1. **All green.** 79/79 tests pass; `ruff`, `format`, `mypy` clean; NIM `doctor` fully healthy.
2. **Submission blocker stays the same:** a real `NEBIUS_API_KEY` + `LLM_PROVIDER=tokenfactory`
   (see the `SUBMISSION FLIP` block in `.env`). After adding the key, re-run
   `doctor --json` (expect exit 0) and `pytest -m live` (expect `tokenfactory_*.json` artifacts).
3. **Phase 3 guard is live and green.** `test_guard.py` (10 tests) passes; the earlier
   `test_report_summary_text`/`test_files` mismatch from 11:38–11:39 was fixed (see git diff on
   `tests/test_guard.py`), and `guard.py` was ruff-formatted.
4. Some live-run artifacts overwrote previously committed evidence files
   (`nvidia_nim_*.json`, `tavily_search.json`) with fresh verification runs — expected, contents supersede.
