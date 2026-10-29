# Demo video script — UpgradePilot (target 2:50)

Only things the repository can prove appear in this script. Times are for a
2:50 cut; no music (rights), narration over screen recording at 1080p.

**Recording/upload status: not recorded; not uploaded to YouTube.** This is a
script, not a completed video or public URL. Record only after public repository
and demo URLs are available; keep the provider disclosure below.

Every shot names the artifact it shows, so nothing on screen is narrated from
memory.

## 0:00–0:15 — The problem

**Screen:** terminal, `python bench/demo_case.py --check` just finished.
Visible text: `old pin pydantic==1.10.22: GREEN (30 passed, 0 failed)`,
`after bump to 2.12.4: ENV_FAIL (exit 4, 0 passed)`.

**Narration:** "One dependency bump and the suite stops importing. The usual
agent 'fix' is to edit the tests until they pass. UpgradePilot upgrades one
dependency and proves the result instead of claiming it."

## 0:15–0:35 — The case is real, and the held-out set was written first

**Screen:** `git log --oneline | tail -3` showing the demo commit, then
`demo/heldout/test_heldout_contract.py` and its 11 test names.

**Narration:** "This is a demo target I wrote — an invoice calculator pinned to
pydantic 1.10.22. Its 11 held-out assertions were committed before the first
agent run and are never copied into the agent's work tree. A model has seen
pydantic migrations before, so this shows the pipeline works; it is not a
benchmark claim."

## 0:35–0:50 — One run, disposable checkout

**Screen:** `upgradepilot upgrade demo/invoicekit --package pydantic --to 2.12.4`
starting; the log shows the old-pin reference suite running GREEN, then the
bump, then `baseline_verify: Breakage confirmed: ENV_FAIL`.

**Narration:** "The target is copied into a disposable checkout with its own
venv. Before the bump it records the old-pin suite as a reference — 30 passed —
then installs 2.12.4 and confirms the breakage."

## 0:50–1:20 — The guard catches a test edit

**Screen:** proof card from the **first** agent run
(`artifacts/demo/.../agent-run1/`): `Final Verdict: CHEATED`, attempt 2 detail
`edit targets the guarded test surface: 'tests/conftest.py'; rolled back 0
file(s)`, guard summary `clean` at attempt 1.

**Narration:** "On the first run the model decided to fix `conftest.py`. Every
test file is hashed before any model call; the patch was rejected, the file was
left untouched, and the run ended CHEATED rather than passing. That is the
whole point: a suite the agent edited cannot certify anything."

## 1:20–1:45 — Retry reaches GREEN, certified by the held-out contract

**Screen:** the second run's proof card: `Final Verdict: GREEN`, iterations 3,
`Applied Patches: src/invoicekit/models.py`, then
`python bench/demo_case.py --table-only` showing `agent | GREEN | 13P/0F/0E |
GREEN (11P/0F)`.

**Narration:** "Same case after one prompt fix: the third attempt migrated the
model layer, the visible suite passed, and the external held-out contract —
which the agent never saw — passed all 11 assertions. Only source was edited."

## 1:45–2:10 — The honest table

**Screen:** `artifacts/demo/.../results.md`:

| bump-only | ENV_FAIL | | single-shot | ENV_FAIL | | agent | GREEN | | agent-run1 | CHEATED |

then `artifacts/phase5/results.md` (benchmark, **no GREEN**).

**Narration:** "Bump-only and single-shot fail on the same case. The agent
reaches GREEN once. On the two third-party benchmark cases nothing reaches
GREEN — those are hard migrations, and the table says so."

## 2:10–2:30 — Provider honesty and the site

**Screen:** the recorded-runs site (`docs/index.html`) with its banner and
"Recorded run" evidence badge, plus the row label "NVIDIA NIM (dev run - not
submission-eligible)".

**Narration:** "These are recorded development runs, not a live demo. The
successful example used NVIDIA NIM; this repository has no Nebius Token Factory
call yet, so it makes no Token Factory success claim. Every status and provider
label is taken from the committed evidence."

## 2:30–2:50 — Close

**Screen:** `pytest tests` → `195 passed, 4 deselected`,
`ruff check src tests bench`, `mypy src tests`, then the comparison page.

**Narration:** "195 offline tests pass, lint and types are clean, and every
result is traceable to JSON. UpgradePilot — an upgrade agent you can audit."

### Recording checklist

- [ ] Never show `.env` or a key prefix beyond what `doctor` masks
- [ ] Keep final export under 3:00 and upload publicly to YouTube; neither is done yet
- [ ] Show keyboard focus once on the site (tab order, skip link)
- [ ] Keep real timings on screen; do not cut the CHEATED run to look better
- [ ] State the provider on screen, not only in narration
