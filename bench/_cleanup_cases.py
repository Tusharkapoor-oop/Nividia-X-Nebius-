import json

with open("bench/cases.json", encoding="utf-8") as f:
    data = json.load(f)

# Keep only verified cases
verified_ids = {"pytest-lazy-fixture-pytest7-to-8", "pydantic-argparse-pydantic1-to-2"}
data["cases"] = [c for c in data["cases"] if c["id"] in verified_ids or c["status"] == "candidate"]

with open("bench/cases.json", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
    f.write("\n")

print("Cleaned up cases. Remaining:")
for c in data["cases"]:
    print(f"  {c['id']}: {c['status']}")
