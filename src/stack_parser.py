"""Java exception stack trace parser."""

import re

from src.models import StackFrame

# Matches: "    at com.example.Foo.bar(Foo.java:42)"
_FRAME_RE = re.compile(
    r"^\s*at\s+"
    r"(?P<class_name>[\w.$]+)"
    r"\."
    r"(?P<method>[\w<>$]+)"
    r"\("
    r"(?P<file>[^:)]+)"
    r"(?::(?P<line>\d+))?"
    r"\)"
)


def parse_stack_trace(text: str) -> list[StackFrame]:
    """Parse a Java exception stack trace into a list of frames.

    Args:
        text: Raw stack trace text.

    Returns:
        Ordered list of StackFrame objects, topmost frame first.
    """
    frames: list[StackFrame] = []
    for raw_line in text.splitlines():
        m = _FRAME_RE.match(raw_line)
        if m:
            frames.append(
                StackFrame(
                    class_name=m.group("class_name"),
                    method=m.group("method"),
                    file=m.group("file"),
                    line=int(m.group("line")) if m.group("line") else 0,
                )
            )
    return frames


def find_business_top_frame(
    frames: list[StackFrame],
    framework_packages: list[str],
) -> StackFrame | None:
    """Return the topmost frame whose class does not match any framework prefix.

    Args:
        frames: Ordered list of frames, topmost first.
        framework_packages: Package prefixes to treat as framework code.

    Returns:
        First non-framework frame, or None if all frames are framework code.
    """
    for frame in frames:
        if not any(frame.class_name.startswith(pkg) for pkg in framework_packages):
            return frame
    return None
