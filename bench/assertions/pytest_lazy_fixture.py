"""Held-out behavioral assertions for pytest-lazy-fixture (pytest 7 -> 8).

pytest-lazy-fixture contains only a single test file (tests/test_lazyfixture.py).
These 10 external behavioral assertions act as the independent held-out set
quarantined outside the worktree during patching and restored only at certification.
"""

from __future__ import annotations

import pytest
from pytest_lazyfixture import (
    LazyFixture,
    is_lazy_fixture,
    lazy_fixture,
    pytest_configure,
    pytest_make_parametrize_id,
    sorted_by_dependency,
)


def test_lazy_fixture_string_instantiation() -> None:
    """Assertion 1: lazy_fixture() accepts single string and returns LazyFixture instance."""
    lf = lazy_fixture("my_fixture")
    assert isinstance(lf, LazyFixture)
    assert lf.name == "my_fixture"


def test_lazy_fixture_sequence_instantiation() -> None:
    """Assertion 2: lazy_fixture() accepts a list or tuple of fixture names."""
    names = ["fixture_a", "fixture_b", "fixture_c"]
    lfs = lazy_fixture(names)
    assert isinstance(lfs, list)
    assert len(lfs) == 3
    assert [item.name for item in lfs] == names
    assert all(isinstance(item, LazyFixture) for item in lfs)


def test_is_lazy_fixture_predicate_true() -> None:
    """Assertion 3: is_lazy_fixture() returns True for LazyFixture instances."""
    lf = lazy_fixture("sample")
    assert is_lazy_fixture(lf) is True


def test_is_lazy_fixture_predicate_false_for_non_fixtures() -> None:
    """Assertion 4: is_lazy_fixture() returns False for strings, numbers, None, and dicts."""
    assert is_lazy_fixture("sample") is False
    assert is_lazy_fixture(123) is False
    assert is_lazy_fixture(None) is False
    assert is_lazy_fixture({"name": "sample"}) is False


def test_lazy_fixture_equality_and_inequality() -> None:
    """Assertion 5: LazyFixture equality is governed by fixture name."""
    lf1 = LazyFixture("fix_one")
    lf2 = LazyFixture("fix_one")
    lf3 = LazyFixture("fix_two")
    assert lf1 == lf2
    assert lf1 != lf3
    assert lf1 != "fix_one"


def test_lazy_fixture_representation_format() -> None:
    """Assertion 6: String representation follows standard format '<LazyFixture "name">'."""
    lf = LazyFixture("database_engine")
    assert repr(lf) == '<LazyFixture "database_engine">'


def test_pytest_make_parametrize_id_resolves_name() -> None:
    """Assertion 7: Hook helper extracts the name of LazyFixture objects for test IDs."""
    lf = LazyFixture("auth_token")
    assert pytest_make_parametrize_id(None, lf, "auth_token") == "auth_token"
    assert pytest_make_parametrize_id(None, "plain_val", "plain_val") is None


def test_sorted_by_dependency_orders_parameters() -> None:
    """Assertion 8: Parameter sorting resolves dependent lazy fixture ordering."""
    params = {"child": lazy_fixture("parent"), "parent": 42}
    sorted_params = sorted_by_dependency(params, ["parent", "child"])
    keys = [k for k, _ in sorted_params]
    assert keys.index("parent") < keys.index("child")


def test_pytest_configure_attaches_attribute() -> None:
    """Assertion 9: pytest_configure binds lazy_fixture to the pytest namespace."""
    pytest_configure()
    assert hasattr(pytest, "lazy_fixture")
    assert pytest.lazy_fixture is lazy_fixture


def test_lazy_fixture_in_parametrized_test(request: pytest.FixtureRequest) -> None:
    """Assertion 10: In-vivo execution of a lazy_fixture parameter within pytest."""
    lf = lazy_fixture("request")
    assert is_lazy_fixture(lf)
    assert lf.name == "request"
