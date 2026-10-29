# Demo case: invoicekit, pydantic 1 → 2

This directory holds the **demo case** — a self-written target used to show the
pipeline running end to end. It is *not* part of the benchmark case set in
`bench/cases.json`, and no benchmark claim is derived from it.

| Path | Visibility | Purpose |
|------|------------|---------|
| `invoicekit/` | the agent's target checkout | original MIT-licensed invoice calculator, pinned to pydantic `1.10.22` |
| `invoicekit/tests/` | visible to the agent (tests are never editable) | 22 tests that pass on pydantic v1 |
| `heldout/` | **outside the work tree and outside every prompt** | 11 behavioural assertions used only for certification |

`heldout/` is committed before the first agent run so the git history shows the
held-out contract existed before any patch was generated. `bench/demo_case.py`
copies it into a scratch checkout *after* the agent run, which is the only time
it is executed against the agent's work.

Because a model may already have seen similar public code (pydantic v1 → v2 is
a very common migration), a GREEN run here shows the pipeline works, not that
the agent generalises to unseen repositories.

Reproduce the demo case's two preconditions yourself with:

```bash
python bench/demo_case.py --check   # old pin GREEN, bumped pin fails, held-out fails
```
