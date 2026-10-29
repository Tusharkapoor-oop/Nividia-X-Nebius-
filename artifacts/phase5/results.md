# Phase 5 strategy comparison

Generated from `artifacts/phase5/<case>/<strategy>/result.json`. Every row is one real run of one strategy on the same pinned checkout for that case; nothing here is estimated.

| Case | Strategy | Provider | Status | Suite | Iterations | LLM calls | Tokens | Cost | Wall |
|------|----------|----------|--------|-------|------------|-----------|--------|------|------|
| pydantic-argparse-pydantic1-to-2 | bump-only | NVIDIA NIM (dev run - not submission-eligible) | ENV_FAIL | 0P/0F/0E (exit 4) | 0 | 0 | 0in/0out | unpriced | 84.9s |
| pydantic-argparse-pydantic1-to-2 | codemod | NVIDIA NIM (dev run - not submission-eligible) | ENV_FAIL | 0P/0F/0E (exit 4) | 0 | 0 | 0in/0out | unpriced | 103.3s |
| pydantic-argparse-pydantic1-to-2 | single-shot | NVIDIA NIM (dev run - not submission-eligible) | ENV_FAIL | 0P/0F/0E (exit 4) | 0 | 1 | 13431in/872out | unpriced | 91.1s |
| pydantic-argparse-pydantic1-to-2 | agent | NVIDIA NIM (dev run - not submission-eligible) | ENV_FAIL | 0P/0F/0E (exit 4) | 5 | 6 | 11189in/1660out | unpriced | 128.4s |
| pytest-lazy-fixture-pytest7-to-8 | bump-only | NVIDIA NIM (dev run - not submission-eligible) | ENV_FAIL | 0P/0F/1E (exit 2) | 0 | 0 | 0in/0out | unpriced | 114.7s |
| pytest-lazy-fixture-pytest7-to-8 | codemod | NVIDIA NIM (dev run - not submission-eligible) | ENV_FAIL | 0P/0F/1E (exit 2) | 0 | 0 | 0in/0out | unpriced | 102.4s |
| pytest-lazy-fixture-pytest7-to-8 | single-shot | NVIDIA NIM (dev run - not submission-eligible) | STUCK | 0P/0F/0E (exit 1) | 0 | 1 | 2861in/1970out | unpriced | 117.0s |
| pytest-lazy-fixture-pytest7-to-8 | agent | NVIDIA NIM (dev run - not submission-eligible) | STUCK | 12P/33F/0E (exit 1) | 5 | 6 | 17765in/8608out | unpriced | 355.8s |

Legend: **bump-only** is the control (no repair), **codemod** is the mechanical rename table, **single-shot** is one model patch attempt, **agent** is the full Phase 4 loop. `unpriced` means the active provider publishes no price for the model, so no dollar figure is claimed.

Resolved environment per case (read from the venv after install):

- `pydantic-argparse-pydantic1-to-2`: pydantic 2.12.4, pytest 9.2.0, python 3.13.15
- `pytest-lazy-fixture-pytest7-to-8`: pytest 8.4.1, python 3.13.15
