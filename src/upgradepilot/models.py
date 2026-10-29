"""Pydantic models for pricing, usage, and cost accounting.

Token usage fields follow OpenAI-compatible /chat/completions responses,
which Token Factory implements. PytestResult models the harness's parse of
a `pytest` invocation's summary line.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMResponse(BaseModel):
    """Normalised chat-completion response."""

    content: str = ""
    usage: TokenUsage = TokenUsage()
    model: str = ""
    finish_reason: str = ""
    raw: dict[str, object] | None = None


class CostRecord(BaseModel):
    """Accumulated spend for one run across tiers.

    ``total_cost_usd`` is only meaningful when every tier was priced from a
    live pricing catalog. Calls against unpriced providers (nvidia-nim) count
    in ``unpriced_calls`` instead of being converted to fake dollars.
    """

    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_cost_usd: float = 0.0
    calls: int = 0
    unpriced_calls: int = 0

    def add_snapshot(self, tokens_in: int, tokens_out: int) -> None:
        self.total_prompt_tokens += tokens_in
        self.total_completion_tokens += tokens_out
        self.calls += 1

    def add_cost(self, cost_usd: float) -> None:
        self.total_cost_usd += cost_usd

    @property
    def total_tokens(self) -> int:
        return self.total_prompt_tokens + self.total_completion_tokens

    @property
    def fully_priced(self) -> bool:
        """True when no call was left unpriced by its provider."""
        return self.unpriced_calls == 0


class PytestResult(BaseModel):
    """Outcome of one pytest invocation, parsed from its own output."""

    exit_code: int
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    xfailed: int = 0
    xpassed: int = 0
    duration_s: float = 0.0
    output_tail: list[str] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    @property
    def collected_anything(self) -> bool:
        total = self.passed + self.failed + self.errors + self.skipped
        return total > 0
