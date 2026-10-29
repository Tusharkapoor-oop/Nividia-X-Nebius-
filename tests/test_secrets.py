"""Unit tests for secret masking and redaction."""

from __future__ import annotations

from upgradepilot.secrets import mask_secret, redact


def test_mask_never_returns_the_tail() -> None:
    masked = mask_secret("tvly-abcdefghijklmnopqrstuvwxyz")
    assert masked == "tvly..."
    assert "wxyz" not in masked


def test_mask_empty_and_short_values() -> None:
    assert mask_secret("") == "<unset>"
    assert mask_secret("   ") == "<unset>"
    assert mask_secret("abc") == "<set-short>"


def test_redact_known_key_shapes() -> None:
    text = "auth=Bearer tvly-abcdefghijklmnopqrstu and sk-abcdefghijklmnop12345"
    scrubbed = redact(text)
    assert "tvly-abcdefghijklmnopqrstu" not in scrubbed
    assert "sk-abcdefghijklmnop12345" not in scrubbed
    assert scrubbed.count("<redacted>") == 2


def test_redact_leaves_ordinary_words_alone() -> None:
    assert redact("pytest 8.4.1 upgrade") == "pytest 8.4.1 upgrade"
