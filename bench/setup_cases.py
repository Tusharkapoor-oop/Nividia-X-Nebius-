import json

cases = [
    {
        "id": "pytest-lazy-fixture-pytest7-to-8",
        "status": "verified-passing-to-failing",
        "source": "https://github.com/TvoroG/pytest-lazy-fixture",
        "commit": "18ec85edb5e27c933733f748c685b2fd083198d7",
        "dep": "pytest",
        "old_pin": "pytest==7.4.4",
        "new_pin": "8.4.1",
        "license": "MIT",
        "license_url": "https://github.com/TvoroG/pytest-lazy-fixture/blob/master/LICENSE",
        "install_repo": True,
        "notes": "pytest 8 removes the hook API this plugin uses (see TvoroG/pytest-lazy-fixture#65; Debian bug 1066727; Backblaze b2-sdk-python #484). Its own tests pass on pytest 7 and fail on pytest 8 during plugin/collection load.",
        "verified": {
            "pre": "GREEN",
            "post": "ENV_FAIL",
            "pre_run_json": "artifacts/phase2/pytest-lazy-fixture-pytest7-to-8/run-20261020T005218-d8c088_*.json",
            "post_run_json": "artifacts/phase2/pytest-lazy-fixture-pytest7-to-8/run-20261020T005240-d79c2e_*.json",
            "events": "artifacts/phase2/pytest-lazy-fixture-pytest7-to-8/events.jsonl",
        },
    },
    {
        "id": "imodmodel-pytest7-to-8",
        "status": "candidate",
        "source": "https://github.com/teamtomo/imodmodel",
        "commit": "HEAD",
        "dep": "pytest",
        "old_pin": "pytest==7.4.4",
        "new_pin": "8.4.1",
        "license": "BSD-3-Clause",
        "license_url": "https://github.com/teamtomo/imodmodel/blob/main/pyproject.toml (license text: 'BSD 3-Clause License')",
        "install_repo": True,
        "repo_install_args": ["-e", "."],
        "pre_install_pins": ["pytest-lazy-fixture==0.6.0"],
        "notes": "teamtomo/imodmodel#11 documents that pytest>=8 breaks pytest-lazy-fixture in its test env, causing failures. pyproject pins nothing for the plugin, so the pinned install reproduces the environment the issue describes. Small pure-python+numpy/pandas repo.",
        "verified": None,
    },
    {
        "id": "pydantic-argparse-pydantic1-to-2",
        "status": "verified-passing-to-failing",
        "source": "https://github.com/SupImDos/pydantic-argparse",
        "commit": "c07199879040f9cfd26f13b2cfbeb8105a3c830f",
        "dep": "pydantic",
        "old_pin": "pydantic==1.10.22",
        "new_pin": "2.12.4",
        "license": "MIT",
        "license_url": "https://github.com/SupImDos/pydantic-argparse/blob/main/LICENSE.md",
        "install_repo": True,
        "repo_install_args": ["-e", "."],
        "pre_install_pins": ["pytest-mock==3.14.1"],
        "notes": "At c0719987 (0.8.0, 2023) the project is Pydantic-v1-only (pydantic>=1.9,<2; SupImDos/pydantic-argparse#56 shows v2 support arrived much later via a shim). Upgrading pydantic to 2.x breaks the v1-only test suite; pytest-mock is a dev-group dep the tests import.",
        "verified": {
            "pre": "GREEN",
            "post": "ENV_FAIL",
            "pre_run_json": "artifacts\\\\phase2\\\\pydantic-argparse-pydantic1-to-2\\\\run-20261020T010048-e721c2_*.json",
            "post_run_json": "artifacts\\\\phase2\\\\pydantic-argparse-pydantic1-to-2\\\\run-20261020T010109-7ea945_*.json",
            "events": "artifacts\\\\phase2\\\\pydantic-argparse-pydantic1-to-2\\\\events.jsonl",
        },
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
]

data = {"cases": cases}

with open("bench/cases.json", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
    f.write("\n")

print("Done! Cases written:")
for c in data["cases"]:
    print("  {}: {}".format(c["id"], c["status"]))
