"""LLM client for OpenAI-compatible chat/completions providers.

Two supported providers (``Settings.llm_provider``):

- ``tokenfactory`` — Nebius Token Factory. Prices/context come from the
  live catalog, and a USD cap is preflighted before every call.
- ``nvidia-nim`` — NVIDIA NIM (build.nvidia.com). The provider publishes
  no machine-readable pricing catalog, so no dollar figure is ever
  computed; instead the run is capped by request count
  (``max_llm_calls_per_run``) and calls are recorded as unpriced.

Cost discipline:
- *Preflight*: the USD cap blocks before any network call (Token Factory) or
  the request cap blocks before any network call (NIM).
- *Confirm*: after each response the exact usage from the API is added to
  the run ledger; USD is booked only for priced tiers.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import httpx

from upgradepilot.config import Settings
from upgradepilot.models import CostRecord, LLMResponse, TokenUsage
from upgradepilot.retry import RetriesExhausted, request_with_retry
from upgradepilot.tiers import ModelTier

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class LLMClientError(Exception):
    """Non-retryable error from the LLM API."""


class SpendingCapExceeded(RuntimeError):
    """Raised before a request when the projected or actual spend would
    exceed the per-run cap."""


def call_cost(usage: TokenUsage, tier: ModelTier) -> float:
    """Price one call's usage at the tier's per-million-token rates."""
    if not tier.is_priced:
        raise LLMClientError(
            f"tier {tier.model_id!r} has no live-catalog prices; "
            "USD costing is refused rather than invented."
        )
    assert tier.input_price_per_m is not None  # narrowed by is_priced
    assert tier.output_price_per_m is not None  # narrowed by is_priced
    input_cost = usage.prompt_tokens / 1_000_000 * tier.input_price_per_m
    output_cost = usage.completion_tokens / 1_000_000 * tier.output_price_per_m
    return input_cost + output_cost


def estimate_prompt_tokens(messages: list[dict[str, str]]) -> int:
    """Deliberately conservative prompt-token estimate for cap preflight.

    Uses ~3 characters per token plus a per-message overhead. It is not a
    tokenizer; it exists only to make the spending cap fail closed. The
    exact usage from the API is what gets booked.
    """
    chars = sum(
        len(str(message.get("role", ""))) + len(str(message.get("content", "")))
        for message in messages
    )
    return (chars + 2) // 3 + 8 * len(messages)


class LLMClient:
    """Thin wrapper around the provider's chat/completions endpoint."""

    def __init__(
        self,
        settings: Settings,
        http_client: httpx.Client | None = None,
        *,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._settings = settings
        self._provider = settings.llm_provider
        self._base_url = (
            settings.nvidia_nim_base_url
            if settings.llm_provider == "nvidia-nim"
            else settings.tokenfactory_base_url
        ).rstrip("/")
        self._http = http_client or httpx.Client(timeout=60.0)
        self._owns_client = http_client is None
        self._headers = {
            "Authorization": f"Bearer {settings.active_api_key}",
            "Content-Type": "application/json",
        }
        self.cost = CostRecord()
        self._sleep: Callable[[float], None] = sleep if sleep is not None else time.sleep

    # ── public API ────────────────────────────────────────────────

    def chat(
        self,
        messages: list[dict[str, str]],
        tier: ModelTier,
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Send a chat-completion request with retry, preflight cap, and
        post-response cost accounting.

        Args:
            messages: OpenAI-compatible chat messages.
            tier: Model and live-catalog pricing for this call.
            temperature: Sampling temperature.
            max_tokens: Completion budget; defaults to ``tier.max_tokens``.

        Raises:
            SpendingCapExceeded: projected or booked spend ≥ cap.
            LLMClientError: non-retryable / exhausted HTTP failure.
        """
        effective_max_tokens = tier.max_tokens if max_tokens is None else max_tokens
        # Preflight: block before any network cost is incurred.
        if self._provider == "nvidia-nim":
            # No public pricing catalog -> a USD projection would be invented.
            # Enforce the configured request-count cap instead.
            if self.cost.calls >= self._settings.max_llm_calls_per_run:
                raise SpendingCapExceeded(
                    f"Run cap reached: {self.cost.calls} call(s) under the "
                    f"{self._provider} request cap "
                    f"({self._settings.max_llm_calls_per_run}); call blocked."
                )
        else:
            est_prompt = estimate_prompt_tokens(messages)
            projected = self.cost.total_cost_usd + call_cost(
                TokenUsage(prompt_tokens=est_prompt, completion_tokens=effective_max_tokens),
                tier,
            )
            if projected >= self._settings.token_cost_cap_usd:
                raise SpendingCapExceeded(
                    f"Projected cost ${projected:.6f} would exceed cap "
                    f"${self._settings.token_cost_cap_usd:.4f} "
                    f"(booked ${self.cost.total_cost_usd:.6f}); call blocked."
                )

        payload: dict[str, Any] = {
            "model": tier.model_id,
            "messages": list(messages),
            "temperature": temperature,
            "max_tokens": effective_max_tokens,
        }
        if self._provider == "nvidia-nim":
            # Nemotron 3/3.5 models reason before answering by default; with a
            # normal max_tokens they can return empty ``content`` when the
            # budget is spent on reasoning. NVIDIA documents this switch for
            # direct answers, which is what the pipeline's JSON/code steps
            # need. Token Factory keeps its default payload.
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        raw = self._post("/chat/completions", json=payload)
        response = self._parse_response(raw)
        self.cost.add_snapshot(response.usage.prompt_tokens, response.usage.completion_tokens)
        # Pricing is a property of the provider, not just the tier object: a
        # NIM call is unpriced even if a caller accidentally passes a tier with
        # catalog prices. Never book an invented dollar figure.
        priced_call = self._provider == "tokenfactory" and tier.is_priced
        if priced_call:
            self.cost.add_cost(call_cost(response.usage, tier))
        else:
            self.cost.unpriced_calls += 1
        if priced_call:
            logger.info(
                "LLM %s | in=%d out=%d | run total $%.6f / $%.4f",
                tier.model_id,
                response.usage.prompt_tokens,
                response.usage.completion_tokens,
                self.cost.total_cost_usd,
                self._settings.token_cost_cap_usd,
            )
        else:
            logger.info(
                "LLM %s | in=%d out=%d | calls %d/%d (unpriced provider)",
                tier.model_id,
                response.usage.prompt_tokens,
                response.usage.completion_tokens,
                self.cost.calls,
                self._settings.max_llm_calls_per_run,
            )
        return response

    def close(self) -> None:
        """Close the underlying HTTP client only if we created it."""
        if self._owns_client:
            self._http.close()

    # ── internals ─────────────────────────────────────────────────

    def _post(self, path: str, json: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        try:
            response = request_with_retry(
                lambda: self._http.request("POST", url, headers=self._headers, json=json),
                retryable_status=_RETRYABLE_STATUS,
                sleep=self._sleep,
            )
        except RetriesExhausted as exc:
            raise LLMClientError(str(exc)) from exc

        if response.status_code == 401:
            raise LLMClientError(
                f"{self._provider} rejected the API key (401). "
                f"Check {self._settings.active_key_name}."
            )
        if response.status_code >= 400:
            raise LLMClientError(
                f"{self._provider} returned {response.status_code}: {response.text[:400]}"
            )
        try:
            raw_json: Any = response.json()
        except ValueError as exc:
            raise LLMClientError(f"{self._provider} returned a non-JSON body.") from exc
        if not isinstance(raw_json, dict):
            raise LLMClientError(f"{self._provider} returned a non-object body.")
        return raw_json

    @staticmethod
    def _parse_response(raw: dict[str, Any]) -> LLMResponse:
        choices: list[dict[str, Any]] = raw.get("choices") or []
        if not choices:
            raise LLMClientError("Provider returned no choices.")
        first = choices[0] or {}
        message = first.get("message") or {}
        content = str(message.get("content", "") or "")
        finish_reason = str(first.get("finish_reason", "") or "")

        usage_raw: dict[str, Any] = raw.get("usage") or {}
        usage = TokenUsage(
            prompt_tokens=int(usage_raw.get("prompt_tokens", 0)),
            completion_tokens=int(usage_raw.get("completion_tokens", 0)),
            total_tokens=int(usage_raw.get("total_tokens", 0)),
        )
        return LLMResponse(
            content=content,
            usage=usage,
            model=str(raw.get("model", "") or ""),
            finish_reason=finish_reason,
            raw=raw,
        )
