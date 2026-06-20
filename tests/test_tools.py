"""Tests for src.tools.read_source and src.tools.find_callers."""

import os

from src.source_index import SourceIndex
from src.tools.find_callers import make_find_callers_tool
from src.tools.read_source import make_read_source_tool

FIXTURES_SRC = os.path.join(os.path.dirname(__file__), "fixtures", "src")


def _make_index() -> SourceIndex:
    idx = SourceIndex(FIXTURES_SRC)
    idx.build()
    return idx


# ---------------------------------------------------------------------------
# read_source tests
# ---------------------------------------------------------------------------


def test_read_source_returns_content() -> None:
    tool = make_read_source_tool(_make_index())
    result = tool.invoke({"class_name": "Demo", "start_line": 1, "end_line": 10})
    assert isinstance(result, str)
    assert "Demo" in result or "class" in result.lower()


def test_read_source_contains_line_numbers() -> None:
    tool = make_read_source_tool(_make_index())
    result = tool.invoke({"class_name": "Demo", "start_line": 1, "end_line": 5})
    assert "1 |" in result or "   1 |" in result


def test_read_source_unknown_class() -> None:
    tool = make_read_source_tool(_make_index())
    result = tool.invoke({"class_name": "NoSuchClass", "start_line": 1, "end_line": 10})
    assert "Cannot resolve" in result or "error" in result.lower()


def test_read_source_clamps_negative_start() -> None:
    tool = make_read_source_tool(_make_index())
    result = tool.invoke({"class_name": "Demo", "start_line": -5, "end_line": 3})
    # Should not raise; should return content starting from line 1
    assert isinstance(result, str)
    assert "Cannot resolve" not in result


def test_read_source_clamps_end_beyond_file() -> None:
    tool = make_read_source_tool(_make_index())
    result = tool.invoke({"class_name": "Demo", "start_line": 1, "end_line": 9999})
    assert isinstance(result, str)
    assert "Cannot resolve" not in result


# ---------------------------------------------------------------------------
# find_callers tests
# ---------------------------------------------------------------------------


def test_find_callers_finds_printname() -> None:
    tool = make_find_callers_tool(FIXTURES_SRC)
    result = tool.invoke({"method_name": "printName"})
    assert isinstance(result, str)
    assert "Demo.java" in result or "demo.java" in result.lower()


def test_find_callers_no_match() -> None:
    tool = make_find_callers_tool(FIXTURES_SRC)
    result = tool.invoke({"method_name": "nonExistentMethodXyz"})
    assert "No callers found" in result


def test_find_callers_result_count_within_limit() -> None:
    tool = make_find_callers_tool(FIXTURES_SRC)
    result = tool.invoke({"method_name": "printName"})
    lines = [ln for ln in result.splitlines() if not ln.startswith("[find_callers]")]
    assert len(lines) <= 20
