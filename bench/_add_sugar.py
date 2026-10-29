import json

with open("bench/cases.json", encoding="utf-8") as f:
    data = json.load(f)

data["cases"].append(
    {
        "id": "pytest-sugar-pytest7-to-8",
        "status": "candidate",
        "source": "https://github.com/FrozenMadd/pytest-sugar",
        "commit": "HEAD",
        "dep": "pytest",
        "old_pin": "pytest==7.4.4",
        "new_pin": "8.4.1",
        "license": "MIT",
        "license_url": "https://github.com/FrozenMadd/pytest-sugar/blob/main/LICENSE",
        "install_repo": True,
        "repo_install_args": ["-e", "."],
        "notes": "FrozenMadd/pytest-sugar is an MIT-licensed pytest plugin that changes pytest output UI. pytest 8 removes old-style hook APIs; this case checks whether pytest-sugars own test suite passes on pytest 7 and fails on pytest 8.",
        "verified": None,
    }
)

with open("bench/cases.json", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
    f.write("\n")

print("Added pytest-sugar case.")
