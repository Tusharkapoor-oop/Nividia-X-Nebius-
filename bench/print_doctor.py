"""Print doctor JSON checks (diagnostic; no secrets — doctor masks keys)."""

import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8-sig"))
# PowerShell Out-File may add a UTF-8 BOM; rewrite plain so committed
# artifacts load with plain json.load everywhere.
path.write_text(json.dumps(data, indent=2), encoding="utf-8")
for entry in data["checks"]:
    name = entry["check"]
    ok = entry.get("ok")
    detail = str(entry.get("detail", ""))[:110]
    print(f"{name}: ok={ok} detail={detail}")
print("overall:", data.get("overall_ok", data.get("ok")))
