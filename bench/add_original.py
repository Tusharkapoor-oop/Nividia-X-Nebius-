import json

with open("bench/cases.json", encoding="utf-8") as f:
    data = json.load(f)

# Add the two original candidates from the Phase 5 context
new_cases = [
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
]

for case in new_cases:
    data["cases"].append(case)

with open("bench/cases.json", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
    f.write("\n")

print("Done! Added pytest-subtests and pytest-mock cases.")
for c in data["cases"]:
    print("  {}: {}".format(c["id"], c["status"]))
