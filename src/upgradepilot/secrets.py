"""Secret masking helpers: never log or store raw API keys."""

from __future__ import annotations

import re

_KEY_RE = re.compile(
    r"\b(?:sk|pk|tvly|napi|nfma)[-_][A-Za-z0-9_\-]{16,}\b",
)


def mask_secret(secret: str, *, visible: int = 4) -> str:
    """Return only the first ``visible`` characters of a configured secret.

    Empty secrets render as ``<unset>`` and very short secrets render as
    ``<set-short>`` so a mask never reveals most of a key.
    """
    value = secret.strip()
    if not value:
        return "<unset>"
    if len(value) <= visible + 4:
        return "<set-short>"
    return f"{value[:visible]}..."


def redact(text: str) -> str:
    """Scrub API-key-shaped tokens from free text before logging or storage."""
    return _KEY_RE.sub("<redacted>", text)
