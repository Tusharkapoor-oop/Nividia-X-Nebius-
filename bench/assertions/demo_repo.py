"""Held-out behavioral assertions for demo repo fixture.

Tests black-box behavior against core arithmetic, string formatting,
and collection utilities. These assertions are never visible to the agent
during the patch loop and certify the repository independently.
"""

from __future__ import annotations

import pytest


def test_demo_addition() -> None:
    """Assertion 1: Positive and negative integer addition."""
    from demo_pkg.mathy import add

    assert add(10, 5) == 15
    assert add(-3, 8) == 5
    assert add(0, 0) == 0


def test_demo_subtraction() -> None:
    """Assertion 2: Subtraction behavior."""
    from demo_pkg.mathy import subtract

    assert subtract(10, 4) == 6
    assert subtract(4, 10) == -6
    assert subtract(0, 5) == -5


def test_demo_multiplication() -> None:
    """Assertion 3: Multiplication properties including zero identity."""
    from demo_pkg.mathy import multiply

    assert multiply(6, 7) == 42
    assert multiply(9, 0) == 0
    assert multiply(-3, -4) == 12


def test_demo_division_exact_and_zero_error() -> None:
    """Assertion 4: Exact division and ZeroDivisionError handling."""
    from demo_pkg.mathy import divide

    assert divide(20, 4) == 5.0
    with pytest.raises(ZeroDivisionError):
        divide(10, 0)


def test_demo_power_exponentiation() -> None:
    """Assertion 5: Power exponentiation rules."""
    from demo_pkg.mathy import power

    assert power(2, 3) == 8
    assert power(5, 0) == 1
    assert power(4, 0.5) == 2.0


def test_demo_clamp_bounds() -> None:
    """Assertion 6: Value clamping within [min_val, max_val] boundaries."""
    from demo_pkg.mathy import clamp

    assert clamp(5, 0, 10) == 5
    assert clamp(-5, 0, 10) == 0
    assert clamp(15, 0, 10) == 10


def test_demo_is_even() -> None:
    """Assertion 7: Parity check for odd, even, and zero."""
    from demo_pkg.mathy import is_even

    assert is_even(4) is True
    assert is_even(7) is False
    assert is_even(0) is True


def test_demo_format_currency() -> None:
    """Assertion 8: Currency formatting with symbols and precision."""
    from demo_pkg.mathy import format_currency

    assert format_currency(1234.56, "$") == "$1,234.56"
    assert format_currency(0, "EUR ") == "EUR 0.00"


def test_demo_parse_kv_pairs() -> None:
    """Assertion 9: Parsing key-value string lists."""
    from demo_pkg.mathy import parse_kv_pairs

    raw = "key1=val1;key2=val2;flag=true"
    parsed = parse_kv_pairs(raw)
    assert parsed == {"key1": "val1", "key2": "val2", "flag": "true"}


def test_demo_chunk_list() -> None:
    """Assertion 10: Partitioning lists into fixed-size chunks."""
    from demo_pkg.mathy import chunk_list

    items = [1, 2, 3, 4, 5, 6, 7]
    chunks = chunk_list(items, 3)
    assert chunks == [[1, 2, 3], [4, 5, 6], [7]]
