import json

with open("bench/cases.json", encoding="utf-8") as f:
    data = json.load(f)

# Keep only verified cases and the original imodmodel candidate
keep_ids = {
    "pytest-lazy-fixture-pytest7-to-8",
    "imodmodel-pytest7-to-8",
    "pydantic-argparse-pydantic1-to-2",
}
data["cases"] = [c for c in data["cases"] if c["id"] in keep_ids]

# Add pytest-doctestplus as a candidate
data["cases"].append(
    {
        "id": "pytest-doctestplus-pytest7-to-8",
        "status": "candidate",
        "source": "https://github.com/pytest-dev/pytest-doctestplus",
        "commit": "HEAD",
        "dep": "pytest",
        "old_pin": "pytest==7.4.4",
        "new_pin": "8.4.1",
        "license": "MIT",
        "license_url": "https://github.com/pytest-dev/pytest-doctestplus/blob/main/LICENSE",
        "install_repo": True,
        "repo_install_args": ["-e", "."],
        "notes": "pytest-dev/pytest-doctestplus is an MIT-licensed pytest plugin for doctest integration. pytest 8 removes old-style hook APIs; this case checks whether pytest-doctestpluss own test suite passes on pytest 7 and fails on pytest 8.",
        "verified": None,
    }
)

with open("bench/cases.json", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
    f.write("\n")

print("Cleaned up and added pytest-doctestplus case. Remaining:")
for c in data["cases"]:
    print(f"  {c['id']}: {c['status']}")
