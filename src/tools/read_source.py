"""read_source tool: read a code snippet from a Java source file."""

from langchain_core.tools import tool

from src.source_index import SourceIndex

_MAX_WINDOW = 20  # default half-window around a target line


def make_read_source_tool(index: SourceIndex):  # type: ignore[return]
    """Return a LangChain tool that reads source lines from the index.

    Args:
        index: Pre-built SourceIndex mapping class names to file paths.

    Returns:
        A LangChain @tool function bound to the given index.
    """

    @tool
    def read_source(class_name: str, start_line: int, end_line: int) -> str:
        """Read a range of lines from a Java source file.

        Returns lines start_line through end_line (1-based, inclusive),
        prefixed with line numbers. The range is clamped to valid file bounds.
        Returns an error message string if the class cannot be resolved.

        Args:
            class_name: Simple or fully-qualified Java class name.
            start_line: First line to read (1-based).
            end_line: Last line to read (1-based, inclusive).
        """
        path = index.resolve(class_name)
        if path is None:
            return f"[read_source] Cannot resolve class '{class_name}' to a source file."

        try:
            with open(path, encoding="utf-8") as f:
                all_lines = f.readlines()
        except OSError as exc:
            return f"[read_source] Cannot read '{path}': {exc}"

        total = len(all_lines)
        # Clamp to valid range (1-based → 0-based index)
        clamped_start = max(1, start_line)
        clamped_end = min(total, end_line)

        if clamped_start > clamped_end:
            return f"[read_source] Requested range [{start_line}, {end_line}] is out of bounds (file has {total} lines)."

        lines = all_lines[clamped_start - 1 : clamped_end]
        numbered = "".join(
            f"{clamped_start + i:4d} | {line}" for i, line in enumerate(lines)
        )
        return f"// {path} (lines {clamped_start}-{clamped_end})\n{numbered}"

    return read_source
