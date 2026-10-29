"""Held-out behavioral assertion suites for benchmark and demo repos."""

from __future__ import annotations

from pathlib import Path

ASSERTIONS_DIR = Path(__file__).parent

CASE_ASSERTION_MAP = {
    "demo": ASSERTIONS_DIR / "demo_repo.py",
    "demo_repo": ASSERTIONS_DIR / "demo_repo.py",
    "pytest-lazy-fixture": ASSERTIONS_DIR / "pytest_lazy_fixture.py",
    "pytest-lazy-fixture-pytest7-to-8": ASSERTIONS_DIR / "pytest_lazy_fixture.py",
    "pydantic-argparse": ASSERTIONS_DIR / "pydantic_argparse.py",
    "pydantic-argparse-pydantic1-to-2": ASSERTIONS_DIR / "pydantic_argparse.py",
}


def get_assertions_for_repo(repo_identifier: str) -> str | None:
    """Return the code of behavioral assertions for a repo/case, if available."""
    normalized = repo_identifier.lower().strip()
    path = CASE_ASSERTION_MAP.get(normalized)
    if path and path.is_file():
        return path.read_text(encoding="utf-8")
    for key, candidate in CASE_ASSERTION_MAP.items():
        if key in normalized and candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    return None
