# Feedback: Nebius Token Factory + NVIDIA Nemotron (draft)

Draft for the hackathon feedback form. It separates what this repository's logs
and files prove from what only the author observed, so nothing is presented as
verified when it is not.

## What the repository proves

- **No billable Nebius call was made in this build.** `NEBIUS_API_KEY` was never
  set (`upgradepilot doctor` reports the `keys` check as failed), so every model
  call recorded in `artifacts/` is an **NVIDIA NIM development call**
  (`integrate.api.nvidia.com`). Token Factory spend: $0.
- **The NVIDIA NIM trial account exposes different models than the Token
  Factory catalog.** `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` and
  `nvidia/Nemotron-3_5-Lightning` are catalog IDs; on NIM, Nano returned 404
  and the working IDs were `nvidia/nemotron-3.5-lightning-30b-a3b` and
  `nvidia/nemotron-3-ultra-550b-a55b` (2026-10-21, `artifacts/phase0/live_calls/`).
  Model names that are valid in one place are not guaranteed valid in the other,
  which makes "same model, different endpoint" assumptions unsafe.
- **NIM publishes no machine-readable pricing catalog.** Token Factory has
  `models_info` with per-M-token prices; for NIM this project deliberately
  records calls as *unpriced* rather than inventing a dollar figure. A public
  pricing/limits endpoint for NIM would remove that gap.
- **Reasoning output can consume the whole budget.** Nemotron 3 requests to NIM
  needed `chat_template_kwargs={"enable_thinking": false}` to return a short
  answer; without it the completion is spent on hidden reasoning. This is worth
  documenting next to the model cards.
- **Context/output limits matter for patch generation.** With a 4k output cap,
  one of four patch attempts on the demo case was truncated mid-JSON and had to
  be rolled back. The run still reached GREEN on a later attempt, but a published
  "max output tokens" figure per model would let clients size prompts correctly.

## Draft response for the hackathon feedback form

**What worked:** The Token Factory catalog exposes model IDs, context limits and
per-token pricing, which let this project validate configured tiers and enforce
a per-run USD cap before and after calls. The provider abstraction keeps this
submission path distinct from NVIDIA NIM development runs.

**What blocked validation:** No Nebius Token Factory key was available in this
build, so we could not run the live Token Factory probes or verify the full
submission path end to end. All recorded successful model runs are explicitly
labelled NVIDIA NIM development runs; they are not Token Factory evidence.

**Most useful improvements:** Make the credit/key activation path and any
payment-method requirement explicit; provide a first-call example that matches
the exact API base URL and model IDs; and publish context, output-token and
reasoning-mode requirements next to each model listing. This project found that
valid Token Factory model IDs do not necessarily match the NVIDIA NIM endpoint's
IDs, and a 4k output cap truncated one demo patch response before a later retry
succeeded.

**Track:** Coding and Agentic Engineering.

## What the author observed (to confirm before submitting)

These are user-side observations from applying for credits; they are **not**
derived from any file in this repository and should be edited to match exactly
what happened:

- Applying the `NEBIUS-DEVPOST-GLOBAL26` promo code required creating a Nebius
  account first, and the credit did not appear immediately.
- Documentation was ambiguous about whether a payment method is required before
  the promo credit can be used, which was the blocking question when setting up
  billing from India.
- Because no key was available in this checkout, the submission path (Token
  Factory) could not be exercised; repository records show NVIDIA NIM
  development runs instead. Confirm/edit this user-side statement before
  submitting.

## What would have changed the outcome

1. A key that works without a card, or a clearly documented card-free trial path.
2. One page listing, per provider: base URL, exact model IDs, context and output
   limits, price per million tokens (or "unpriced"), and whether reasoning must
   be disabled explicitly.
3. A short "first successful call" snippet that is copy-pasteable with the key
   from the dashboard, so an account can be validated before credits land.
