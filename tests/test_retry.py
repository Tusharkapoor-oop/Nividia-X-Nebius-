"""Unit tests for the retry policy."""

from __future__ import annotations

import httpx
import pytest

from upgradepilot.retry import RetriesExhausted, request_with_retry


def test_gives_up_after_max_attempts() -> None:
    sleeps: list[float] = []
    attempts = {"n": 0}

    def always_500() -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(500)

    with pytest.raises(RetriesExhausted):
        request_with_retry(
            always_500,
            max_attempts=3,
            retryable_status={500},
            sleep=sleeps.append,
        )
    assert attempts["n"] == 3
    assert len(sleeps) == 2


def test_success_after_failures() -> None:
    called = {"n": 0}

    def flaky() -> httpx.Response:
        called["n"] += 1
        return httpx.Response(503 if called["n"] < 3 else 200)

    response = request_with_retry(
        flaky,
        max_attempts=5,
        retryable_status={503},
        sleep=lambda _delay: None,
    )
    assert called["n"] == 3
    assert response.status_code == 200


def test_retry_after_header_is_honoured() -> None:
    sleeps: list[float] = []
    calls = {"n": 0}

    def rate_limited() -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200)

    response = request_with_retry(
        rate_limited,
        max_attempts=2,
        retryable_status={429},
        sleep=sleeps.append,
    )
    assert response.status_code == 200
    assert sleeps and sleeps[0] >= 7.0
