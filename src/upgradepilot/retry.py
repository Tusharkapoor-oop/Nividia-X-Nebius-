"""Shared HTTP retry policy with exponential backoff.

Used by both the Token Factory client (host writes timeout: non-retryable,
server faults: retryable) and the Tavily client (honours ``Retry-After``).
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable

import httpx

logger = logging.getLogger(__name__)


class RetriesExhausted(RuntimeError):
    """All retry attempts for a request failed."""


def request_with_retry(
    send: Callable[[], httpx.Response],
    *,
    max_attempts: int = 4,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    retryable_status: frozenset[int] | set[int] = frozenset({429, 500, 502, 503, 504}),
    respect_retry_after: bool = True,
    sleep: Callable[[float], None] = time.sleep,
) -> httpx.Response:
    """Run ``send()`` with retry/backoff and return the first final response.

    Args:
        send: Zero-arg callable performing one HTTP request. Must not close
            the client between attempts.
        max_attempts: Total attempts including the first.
        base_delay: Initial backoff delay in seconds.
        max_delay: Upper bound for a single sleep.
        retryable_status: Status codes that trigger a retry.
        respect_retry_after: Honour a numeric ``Retry-After`` header.
        sleep: Injectable for tests (default ``time.sleep``).

    Returns:
        The first response with a non-retryable status.

    Raises:
        RetriesExhausted: when all attempts returned retryable statuses.
        httpx.TimeoutException | httpx.HTTPError: propagated after the final
            attempt so callers can classify them.
    """
    last_exc: httpx.HTTPError | None = None
    last_response: httpx.Response | None = None

    for attempt in range(max_attempts):
        try:
            response = send()
            if response.status_code not in retryable_status:
                return response
            last_response = response
            # ``Response.request`` raises when the response was built without a
            # request (e.g. a test double), so read the private attribute.
            request_meta = getattr(response, "_request", None)
            method = getattr(request_meta, "method", "?")
            url = getattr(request_meta, "url", "?")
            logger.warning(
                "HTTP %d from %s %s (attempt %d/%d)",
                response.status_code,
                method,
                url,
                attempt + 1,
                max_attempts,
            )
        except (httpx.TimeoutException, httpx.HTTPError) as exc:
            last_exc = exc
            logger.warning(
                "HTTP error on attempt %d/%d: %s: %s",
                attempt + 1,
                max_attempts,
                type(exc).__name__,
                exc,
            )

        if attempt < max_attempts - 1:
            delay = min(max_delay, base_delay * (2**attempt)) + random.uniform(0, 0.25)
            if respect_retry_after and last_response is not None:
                retry_after = last_response.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    delay = max(delay, float(retry_after))
            logger.info("Retrying in %.2fs", delay)
            sleep(delay)

    if last_response is not None:
        raise RetriesExhausted(
            f"All {max_attempts} attempts failed; final status {last_response.status_code}"
        ) from last_exc
    raise RetriesExhausted(f"All {max_attempts} attempts failed") from last_exc
