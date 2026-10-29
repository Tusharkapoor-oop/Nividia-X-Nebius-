import json

with open("bench/cases.json", encoding="utf-8") as f:
    data = json.load(f)

# Remove any existing pytest-timeout case first
data["cases"] = [c for c in data["cases"] if c["id"] != "pytest-timeout-pytest7-to-8"]

data["cases"].append(
    {
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
        "notes": "pytest-dev/pytest-timeout is a widely-used MIT-licensed pytest plugin. pytest 8 removes old-style hook APIs; this case checks whether pytest-timeouts own test suite passes on pytest 7 and fails on pytest 8.",
        "verified": None,
    }
)

with open("bench/cases.json", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
    f.write("\n")

print("Added pytest-timeout case. Total cases:", len(data["cases"]))
for c in data["cases"]:
    print(f"  {c['id']}: {c['status']}")
