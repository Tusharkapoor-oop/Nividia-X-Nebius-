import json
import os

# Read existing cases.json if it exists, otherwise start fresh
cases_path = "bench/cases.json"
cases_data = {"cases": []}

if os.path.exists(cases_path):
    with open(cases_path, encoding="utf-8") as f:
        existing = json.load(f)
        if isinstance(existing, dict) and "cases" in existing:
            cases_data = existing
        elif isinstance(existing, list):
            cases_data = {"cases": existing}

# Define the new cases to add
new_cases = [
    {
        "id": "pytest-html-pytest7-to-8",
        "status": "candidate",
        "source": "https://github.com/pytest-dev/pytest-html",
        "commit": "HEAD",
        "dep": "pytest",
        "old_pin": "pytest==7.4.4",
        "new_pin": "8.4.1",
        "license": "MIT",
        "license_url": "https://github.com/pytest-dev/pytest-html/blob/main/LICENSE",
        "install_repo": True,
        "repo_install_args": ["-e", "."],
        "notes": "pytest-dev/pytest-html is an MIT-licensed pytest plugin for HTML reporting. pytest 8 removes old-style hook APIs; this case checks whether pytest-html's own test suite passes on pytest 7 and fails or gets stuck on pytest 8.",
        "verified": None,
    },
    {
        "id": "pytest-subtests-pytest7-to-8",
        "status": "candidate",
        "source": "https://github.com/pytest-dev/pytest-subtests",
        "commit": "HEAD",
        "dep": "pytest",
        "old_pin": "pytest==7.4.4",
        "new_pin": "8.4.1",
        "license": "MIT",
        "license_url": "https://github.com/pytest-dev/pytest-subtests/blob/main/LICENSE",
        "install_repo": True,
        "repo_install_args": ["-e", "."],
        "notes": "pytest-dev/pytest-subtests is an MIT-licensed pytest plugin for running subtests. pytest 8 removes old-style hook APIs; this case checks whether pytest-subtests' own test suite passes on pytest 7 and fails or gets stuck on pytest 8.",
        "verified": None,
    },
    {
        "id": "pytest-mock-pytest7-to-8",
        "status": "candidate",
        "source": "https://github.com/pytest-dev/pytest-mock",
        "commit": "HEAD",
        "dep": "pytest",
        "old_pin": "pytest==7.4.4",
        "new_pin": "8.4.1",
        "license": "MIT",
        "license_url": "https://github.com/pytest-dev/pytest-mock/blob/main/LICENSE",
        "install_repo": True,
        "repo_install_args": ["-e", "."],
        "notes": "pytest-dev/pytest-mock is the official mock plugin for pytest. pytest 8 removes old-style hook APIs; this case checks whether pytest-mock's own test suite passes on pytest 7 and fails or gets stuck on pytest 8.",
        "verified": None,
    },
    {
        "id": "pytest-order-pytest7-to-8",
        "status": "candidate",
        "source": "https://github.com/pytest-dev/pytest-order",
        "commit": "HEAD",
        "dep": "pytest",
        "old_pin": "pytest==7.4.4",
        "new_pin": "8.4.1",
        "license": "MIT",
        "license_url": "https://github.com/pytest-dev/pytest-order/blob/main/LICENSE",
        "install_repo": True,
        "repo_install_args": ["-e", "."],
        "notes": "pytest-dev/pytest-order is an MIT-licensed pytest plugin for controlling test execution order. pytest 8 removes old-style hook APIs; this case checks whether pytest-order's own test suite passes on pytest 7 and fails or gets stuck on pytest 8.",
        "verified": None,
    },
]

# Merge new cases, avoiding duplicates by id
existing_ids = {c["id"] for c in cases_data["cases"]}
for c in new_cases:
    if c["id"] not in existing_ids:
        cases_data["cases"].append(c)

# Write back
with open(cases_path, "w", encoding="utf-8") as f:
    json.dump(cases_data, f, indent=2)
    f.write("\n")

print("Cases updated. Total cases:", len(cases_data["cases"]))
for c in cases_data["cases"]:
    print("  {}: {}".format(c["id"], c["status"]))
