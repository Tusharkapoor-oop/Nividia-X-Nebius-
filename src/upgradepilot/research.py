"""Tavily search client for migration guides and changelogs.

Auth uses the current Tavily scheme: ``Authorization: Bearer tvly-...``
header; the body contains only request parameters. Verified live on
2026-10-21: a ``basic`` search returned 3 results and reported 1 credit.

Pricing note from Tavily's public docs: ``basic`` / ``fast`` / ``ultra-fast``
depths cost 1 API credit per request; ``advanced`` costs 2. Only ``basic`` has
been exercised live so far.
"""

from __future__ import annotations

import logging
from typing import Literal

import httpx
from pydantic import BaseModel, Field

from upgradepilot.config import Settings
from upgradepilot.retry import RetriesExhausted, request_with_retry

logger = logging.getLogger(__name__)

_TAVILY_SEARCH_URL = "https://api.tavily.com/search"
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_PLAN_LIMIT_STATUS = {432, 433}


class TavilyError(Exception):
    """Error from the Tavily API (bad key, exhausted plan, malformed…)."""


class TavilyHit(BaseModel):
    """One search result."""

    title: str = ""
    url: str = ""
    content: str = ""
    score: float = 0.0
    published_date: str | None = None


class TavilySearchResult(BaseModel):
    """Structured response from one Tavily search call."""

    query: str
    answer: str = ""
    results: list[TavilyHit] = Field(default_factory=list)
    credits_used: int | None = None
    response_time_s: float = 0.0
    raw: dict[str, object] | None = None

    def summary(self) -> str:
        """Concatenate result snippets into a single context string."""
        parts: list[str] = []
        for r in self.results:
            parts.append(f"### {r.title}\n{r.content}\nSource: {r.url}\n")
        return "\n".join(parts)


class TavilyClient:
    """Search client with retry/backoff and Retry-After support."""

    def __init__(self, settings: Settings, http_client: httpx.Client | None = None) -> None:
        self._api_key = settings.tavily_api_key
        self._http = http_client or httpx.Client(timeout=30.0)
        self._owns_client = http_client is None

    def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        search_depth: Literal["basic", "fast", "ultra-fast", "advanced"] = "basic",
    ) -> TavilySearchResult:
        """Run one search. Raises TavilyError on failure."""
        headers = {"Authorization": f"Bearer {self._api_key}"}
        body: dict[str, object] = {
            "query": query,
            "search_depth": search_depth,
            "max_results": max_results,
            "include_usage": True,
        }

        try:
            response = request_with_retry(
                lambda: self._http.post(_TAVILY_SEARCH_URL, headers=headers, json=body),
                retryable_status=_RETRYABLE_STATUS,
            )
        except RetriesExhausted as exc:
            raise TavilyError(str(exc)) from exc

        if response.status_code in _PLAN_LIMIT_STATUS:
            raise TavilyError(
                f"Tavily plan/pay-as-you-go limit reached (HTTP {response.status_code}): "
                f"{response.text[:300]}"
            )
        if response.status_code == 401:
            raise TavilyError("Tavily rejected the API key (401). Check TAVILY_API_KEY.")
        if response.status_code >= 400:
            raise TavilyError(f"Tavily returned {response.status_code}: {response.text[:300]}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise TavilyError("Tavily returned a non-JSON body.") from exc
        if not isinstance(payload, dict):
            raise TavilyError("Tavily returned a non-object body.")
        raw_results = payload.get("results") or []
        if not isinstance(raw_results, list):
            raise TavilyError("Tavily returned a malformed results field.")
        results = [
            TavilyHit(
                title=str(r.get("title") or ""),
                url=str(r.get("url") or ""),
                content=str(r.get("content") or ""),
                score=float(r.get("score") or 0.0),
                published_date=r.get("published_date"),
            )
            for r in raw_results
            if isinstance(r, dict)
        ]
        raw_usage = payload.get("usage") or {}
        usage: dict[str, object] = raw_usage if isinstance(raw_usage, dict) else {}
        raw_credits = usage.get("credits")
        credits_used = raw_credits if isinstance(raw_credits, int) else None
        raw_time = payload.get("response_time")
        response_time = float(raw_time) if isinstance(raw_time, (int, float, str)) else 0.0
        parsed = TavilySearchResult(
            query=str(payload.get("query") or query),
            answer=str(payload.get("answer") or ""),
            results=results,
            credits_used=credits_used,
            response_time_s=response_time,
            raw=payload,
        )
        logger.info(
            "Tavily '%s': %d results, %s credit(s)",
            query,
            len(parsed.results),
            parsed.credits_used,
        )
        return parsed

    def close(self) -> None:
        """Close the underlying HTTP client only if we created it."""
        if self._owns_client:
            self._http.close()
