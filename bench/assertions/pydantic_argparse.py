"""Held-out behavioral assertions for pydantic-argparse (pydantic 1 -> 2).

Exercises ArgumentParser declaration, typed parsing, flags, lists, validation,
and metadata. Quarantined outside the worktree during patching and restored
at certification.
"""

from __future__ import annotations

import pydantic_argparse
import pytest
from pydantic import BaseModel, Field
from pydantic_argparse import ArgumentParser


class SimpleConfig(BaseModel):
    name: str = Field(description="Name of the service")
    port: int = Field(default=8080, description="Server port")
    debug: bool = Field(default=False, description="Enable debug mode")


class MultiFieldConfig(BaseModel):
    timeout: float = Field(default=30.0)
    tags: list[str] = Field(default_factory=list)


def test_argument_parser_initialization() -> None:
    """Assertion 1: ArgumentParser accepts a Pydantic model class."""
    parser = ArgumentParser(model=SimpleConfig, description="Test parser")
    assert parser.model is SimpleConfig


def test_parse_required_string_argument() -> None:
    """Assertion 2: Parsing required string option returns populated model."""
    parser = ArgumentParser(model=SimpleConfig)
    result = parser.parse_typed_args(["--name", "gateway"])
    assert result.name == "gateway"
    assert result.port == 8080
    assert result.debug is False


def test_parse_integer_override() -> None:
    """Assertion 3: Parsing integer converts string argument to int."""
    parser = ArgumentParser(model=SimpleConfig)
    result = parser.parse_typed_args(["--name", "worker", "--port", "9000"])
    assert result.name == "worker"
    assert result.port == 9000


def test_parse_boolean_flag_true() -> None:
    """Assertion 4: Boolean flags set True when passed."""
    parser = ArgumentParser(model=SimpleConfig)
    result = parser.parse_typed_args(["--name", "app", "--debug"])
    assert result.debug is True


def test_parse_float_field() -> None:
    """Assertion 5: Floating point field parsing and type casting."""
    parser = ArgumentParser(model=MultiFieldConfig)
    result = parser.parse_typed_args(["--timeout", "12.5"])
    assert result.timeout == 12.5


def test_parse_list_field() -> None:
    """Assertion 6: Sequence/list argument parsing."""
    parser = ArgumentParser(model=MultiFieldConfig)
    result = parser.parse_typed_args(["--tags", "api", "auth", "prod"])
    assert result.tags == ["api", "auth", "prod"]


def test_parse_missing_required_argument_exits() -> None:
    """Assertion 7: Missing required arguments cause parser to exit."""
    parser = ArgumentParser(model=SimpleConfig)
    with pytest.raises(SystemExit):
        parser.parse_typed_args([])


def test_parse_invalid_integer_type_exits() -> None:
    """Assertion 8: Invalid argument types (e.g. non-numeric for int) cause exit."""
    parser = ArgumentParser(model=SimpleConfig)
    with pytest.raises(SystemExit):
        parser.parse_typed_args(["--name", "svc", "--port", "not-a-number"])


def test_package_metadata_attributes() -> None:
    """Assertion 9: Package re-exports valid metadata constants."""
    assert hasattr(pydantic_argparse, "__title__")
    assert hasattr(pydantic_argparse, "__version__")
    assert hasattr(pydantic_argparse, "__license__")
    assert pydantic_argparse.__title__ == "pydantic-argparse"


def test_parser_description_and_prog() -> None:
    """Assertion 10: ArgumentParser preserves description metadata."""
    desc = "Custom CLI Description"
    parser = ArgumentParser(model=SimpleConfig, description=desc)
    assert parser.description == desc
