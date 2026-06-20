"""Tests for src.source_index."""

import os
from pathlib import Path

import pytest

from src.source_index import SourceIndex

FIXTURES_SRC = os.path.join(os.path.dirname(__file__), "fixtures", "src")


@pytest.fixture()
def index() -> SourceIndex:
    idx = SourceIndex(FIXTURES_SRC)
    idx.build()
    return idx


def test_resolve_simple_name(index: SourceIndex) -> None:
    path = index.resolve("Demo")
    assert path is not None
    assert path.endswith("Demo.java")
    assert os.path.isabs(path)


def test_resolve_fully_qualified_name(index: SourceIndex) -> None:
    path = index.resolve("com.example.Demo")
    assert path is not None
    assert path.endswith("Demo.java")


def test_resolve_unknown_class(index: SourceIndex) -> None:
    assert index.resolve("NoSuchClass") is None


def test_resolve_before_build() -> None:
    idx = SourceIndex(FIXTURES_SRC)
    assert idx.resolve("Demo") is None


def test_resolve_empty_string(index: SourceIndex) -> None:
    assert index.resolve("") is None


def test_build_with_extra_roots(tmp_path: Path) -> None:
    extra = str(tmp_path)
    java_file = tmp_path / "Extra.java"
    java_file.write_text("public class Extra {}")

    idx = SourceIndex(FIXTURES_SRC, extra_roots=[extra])
    idx.build()

    assert idx.resolve("Extra") is not None
    assert idx.resolve("Demo") is not None
