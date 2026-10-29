import json

cases_path = "bench/cases.json"
with open(cases_path, encoding="utf-8") as f:
    data = json.load(f)

new_case = {
    "id": "pytest-timeout-pytest7-to-8",
    "status": "candidate",
    "source": "https://github.com/pytest-dev/pytest-timeout",
    "commit": "HEAD",
    "dep": "pytest",
    "old_pin": "pytest==7.4.4",
    "new_pin": "8.4.1",
    "license": "MIT",
    "license_url": "https://github.com/pytest-dev/pytest-timeout/blob/main/LICENSE",
    "install_repo": True,
    "repo_install_args": ["-e", "."],
    "notes": "pytest-dev/pytest-timeout is an MIT-licensed pytest plugin for timeout control. pytest 8 removes old-style hook APIs; this case checks whether pytest-timeout's own test suite passes on pytest 7 and fails or gets stuck on pytest 8.",
    "verified": None,
}

# Check for duplicate
existing_ids = {c["id"] for c in data["cases"]}
if new_case["id"] not in existing_ids:
    data["cases"].append(new_case)
    with open(cases_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    print("Added pytest-timeout-pytest7-to-8")
else:
    print("Already exists")

# Print all cases
for c in data["cases"]:
    print("  {}: {}".format(c["id"], c["status"]))
