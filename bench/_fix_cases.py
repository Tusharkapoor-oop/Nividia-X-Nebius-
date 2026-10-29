import json

with open("bench/cases.json", encoding="utf-8") as f:
    data = json.load(f)

# Remove pytest-randomly case
data["cases"] = [c for c in data["cases"] if c["id"] != "pytest-randomly-pytest7-to-8"]

with open("bench/cases.json", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
    f.write("\n")

print("Removed pytest-randomly. Remaining cases:")
for c in data["cases"]:
    print(f"  {c['id']}: {c['status']}")
