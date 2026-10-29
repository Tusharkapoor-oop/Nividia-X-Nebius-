# UpgradePilot Phase 0 artifacts

Everything in this folder is produced by real runs of real code in this
repo — never hand-written.

- `catalog/models_info_snapshot_2026-10-20.json`
  Raw JSON from GET https://tokenfactory.nebius.com/api/public/models_info
  (public endpoint, no API key needed; 28 model descriptors, 5 NVIDIA).
  SHA256 `8527a31e3d6b1bbd6b8f241c95cd0f96d841b26ecdaef9f9fec2c5604c52cb8e`.
  The 2026-10-19 snapshot is kept for comparison.

- `probe_tokenfactory_models_unauthorized.json`
  GET https://api.tokenfactory.nebius.com/v1/models without a key → HTTP 401
  (`token is not present`), captured with `curl.exe` on 2026-10-20.

- `probe_tavily_unauthorized.json`
  POST https://api.tavily.com/search without a key → HTTP 401, captured with
  `curl.exe` on 2026-10-20. `tavily_probe_payload.json` is the exact request
  body used.

- `web_healthz.txt`
  Response + status from a real uvicorn process serving
  `upgradepilot.web.app:create_app` on 127.0.0.1:8765.

- `doctor_no_keys.json`
  Output of `upgradepilot doctor --json` *without* API keys configured.
  `pass:false` and exit code 1 are expected here: the `keys` check fails while
  catalog and tier-pricing checks still show what is live.

- `doctor_tavily_only.json`
  `doctor --json` with a real Tavily key and no Nebius key: Tavily search
  passes (1 credit), the Nebius check is skipped, and `pass:false` remains.

- `live_calls/tavily_search.json`
  Raw parsed result of one real Tavily search on 2026-10-21: 3 results,
  1 credit, 3.44 s.

- `nvidia_probe/`
  Development-only probe against NVIDIA's `integrate.api.nvidia.com`:
  `models.json` (83 models) and `chat_ultra.json` (HTTP 200 for
  `nvidia/nemotron-3-ultra-550b-a55b`). This is **not** a Token Factory call
  and does not satisfy hackathon eligibility.

- `live_calls/` (created only by `pytest -m live` once `.env` exists)
  `tokenfactory_{cheap,default,strong}.json`: one real chat completion per
  tier with usage + cumulative cost. `tavily_search.json`: one real
  Tavily search with credits used and result URLs.

Never place any API key in this folder.
