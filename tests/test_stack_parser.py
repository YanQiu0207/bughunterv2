"""Tests for src.stack_parser."""

import os

import pytest

from src.stack_parser import find_business_top_frame, parse_stack_trace

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
STACK_TRACE_FILE = os.path.join(FIXTURE_DIR, "stack_trace.txt")

_FRAMEWORK_PACKAGES = [
    "java.",
    "javax.",
    "sun.",
    "com.sun.",
    "org.springframework.",
    "org.apache.",
    "org.slf4j.",
]


@pytest.fixture()
def canonical_stack() -> str:
    with open(STACK_TRACE_FILE, encoding="utf-8") as f:
        return f.read()


def test_parse_stack_trace_returns_three_frames(canonical_stack: str) -> None:
    frames = parse_stack_trace(canonical_stack)
    assert len(frames) == 3


def test_parse_stack_trace_topmost_frame(canonical_stack: str) -> None:
    frames = parse_stack_trace(canonical_stack)
    top = frames[0]
    assert top.class_name == "Demo"
    assert top.method == "printName"
    assert top.file == "Demo.java"
    assert top.line == 10


def test_parse_stack_trace_frame_order(canonical_stack: str) -> None:
    frames = parse_stack_trace(canonical_stack)
    assert [f.method for f in frames] == ["printName", "handle", "main"]


def test_find_business_top_frame_canonical(canonical_stack: str) -> None:
    frames = parse_stack_trace(canonical_stack)
    biz_frame = find_business_top_frame(frames, _FRAMEWORK_PACKAGES)
    assert biz_frame is not None
    assert biz_frame.class_name == "Demo"
    assert biz_frame.method == "printName"


def test_find_business_top_frame_skips_framework() -> None:
    from src.models import StackFrame

    frames = [
        StackFrame(class_name="org.springframework.Foo", method="bar", file="Foo.java", line=1),
        StackFrame(class_name="com.company.Service", method="doWork", file="Service.java", line=5),
    ]
    result = find_business_top_frame(frames, _FRAMEWORK_PACKAGES)
    assert result is not None
    assert result.class_name == "com.company.Service"


def test_find_business_top_frame_all_framework() -> None:
    from src.models import StackFrame

    frames = [
        StackFrame(class_name="java.lang.Thread", method="run", file="Thread.java", line=1),
    ]
    assert find_business_top_frame(frames, _FRAMEWORK_PACKAGES) is None


def test_parse_stack_trace_empty_input() -> None:
    assert parse_stack_trace("") == []


def test_parse_stack_trace_no_frames() -> None:
    assert parse_stack_trace("Exception in thread main java.lang.NullPointerException") == []


def test_parse_stack_trace_native_method_frame() -> None:
    text = (
        "java.lang.NullPointerException\n"
        "\tat sun.reflect.NativeMethodAccessorImpl.invoke0(Native Method)\n"
        "\tat com.example.Service.process(Service.java:42)\n"
    )
    frames = parse_stack_trace(text)
    assert len(frames) == 2
    assert frames[0].class_name == "sun.reflect.NativeMethodAccessorImpl"
    assert frames[0].method == "invoke0"
    assert frames[0].line == 0  # sentinel: no source line available


def test_find_business_top_frame_empty_frames() -> None:
    assert find_business_top_frame([], _FRAMEWORK_PACKAGES) is None


def test_find_business_top_frame_empty_framework_packages() -> None:
    from src.models import StackFrame

    frames = [
        StackFrame(class_name="java.lang.Thread", method="run", file="Thread.java", line=1),
        StackFrame(class_name="com.company.Foo", method="bar", file="Foo.java", line=5),
    ]
    # Empty framework list → no filtering → first frame is returned
    result = find_business_top_frame(frames, [])
    assert result is not None
    assert result.class_name == "java.lang.Thread"
