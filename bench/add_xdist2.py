import json

with open("bench/cases.json", encoding="utf-8") as f:
    data = json.load(f)

# Remove pytest-order case since we're switching to xdist
data["cases"] = [c for c in data["cases"] if c["id"] != "pytest-order-pytest7-to-8"]

new_case = {
    "id": "pytest-xdist-pytest7-to-8",
    "status": "candidate",
    "source": "https://github.com/pytest-dev/pytest-xdist",
    "commit": "HEAD",
    "dep": "pytest",
    "old_pin": "pytest==7.4.4",
    "new_pin": "8.4.1",
    "license": "MIT",
    "license_url": "https://github.com/pytest-dev/pytest-xdist/blob/main/LICENSE",
    "install_repo": True,
    "repo_install_args": ["-e", "."],
    "notes": "pytest-dev/pytest-xdist is a widely-used MIT-licensed pytest plugin for distributed testing. pytest 8 removes old-style hook APIs; this case checks whether pytest-xdist's own test suite passes on pytest 7 and fails or gets stuck on pytest 8.",
    "verified": None,
}

data["cases"].append(new_case)

with open("bench/cases.json", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
    f.write("\n")

print("Done! Added pytest-xdist case.")
for c in data["cases"]:
    print("  {}: {}".format(c["id"], c["status"]))
