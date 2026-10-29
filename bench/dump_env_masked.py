"""Print .env keys, masking every KEY/SECRET/TOKEN value (prefix shape only).

Diagnostic only; never prints a secret value.
"""

from pathlib import Path

for raw in Path(".env").read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, _, value = line.partition("=")
    key = key.strip()
    value = value.strip().strip('"').strip("'")
    if not value:
        print(f"{key}: (empty)")
    elif "KEY" in key.upper() or "SECRET" in key.upper() or "TOKEN" in key.upper():
        head = "".join(ch for ch in value[:10] if ch.isalnum() or ch == "-")
        print(f"{key}: SET (starts with {head}..., length {len(value)})")
    else:
        print(f"{key}: {value}")
