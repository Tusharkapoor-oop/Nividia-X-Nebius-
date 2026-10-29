"""Inspect catalog snapshot structure (diagnostic)."""

import json
from pathlib import Path

data = json.loads(
    Path("artifacts/phase0/catalog/models_info_snapshot_2026-10-20.json").read_text(
        encoding="utf-8"
    )
)
print("count:", len(data))
first = data[0]
print("entry keys:", sorted(first.keys()))
for entry in data:
    blob = json.dumps(entry)
    if "emotron" in blob.lower():
        print("---")
        print(json.dumps(entry, indent=1)[:900])
