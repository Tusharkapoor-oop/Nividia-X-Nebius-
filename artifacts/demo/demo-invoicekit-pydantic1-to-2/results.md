# Demo case: invoicekit, pydantic 1.10.22 -> 2.12.4

Self-written demo target (`demo/invoicekit`), not a benchmark case. Generated only from `artifacts/demo/<case>/<strategy>/result.json`.

| Strategy | Provider | Status | Visible suite | Held-out contract | LLM calls | Wall |
|----------|----------|--------|---------------|-------------------|-----------|------|
| bump-only | NVIDIA NIM (dev run - not submission-eligible) | ENV_FAIL | 0P/0F/0E (exit 4) | ENV_FAIL (0P/0F) | 0 | 86.7s |
| single-shot | NVIDIA NIM (dev run - not submission-eligible) | ENV_FAIL | 0P/0F/0E (exit 4) | ENV_FAIL (0P/0F) | 1 | 89.8s |
| agent | NVIDIA NIM (dev run - not submission-eligible) | GREEN | 13P/0F/0E (exit 0) | GREEN (11P/0F) | 4 | 126.4s |
| agent-run1 | NVIDIA NIM (dev run - not submission-eligible) | CHEATED | 0P/0F/0E (exit 4) | ENV_FAIL (0P/0F) | 3 | 91.6s |

Environment (read from the case venv): pydantic 2.12.4, pytest 9.2.0, python 3.13.15

`held-out contract` is `demo/heldout/test_heldout_contract.py`, copied into a scratch directory outside the checkout and run against the final tree. The agent never sees it.
