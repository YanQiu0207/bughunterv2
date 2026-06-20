"""find_callers tool: search for method call sites in Java source files."""

import os

from langchain_core.tools import tool

_MAX_RESULTS = 20


def make_find_callers_tool(src_dir: str):  # type: ignore[return]
    """Return a LangChain tool that searches for callers of a method.

    Searches all .java files under src_dir for occurrences of `method_name(`.
    Results may include false positives (overloaded or same-named methods in
    other classes); the agent filters based on source context.

    Args:
        src_dir: Root directory to search recursively.

    Returns:
        A LangChain @tool function bound to the given src_dir.
    """

    @tool
    def find_callers(method_name: str) -> str:
        """Find call sites of a Java method by name.

        Searches all .java files under the source directory for occurrences
        of `method_name(`. Returns up to 20 matching file:line entries.
        Results may include overloaded or same-named methods in other classes.

        Args:
            method_name: Method name to search for (without parentheses).
        """
        pattern = f"{method_name}("
        matches: list[str] = []

        for dirpath, _, filenames in os.walk(src_dir):
            for filename in filenames:
                if not filename.endswith(".java"):
                    continue
                filepath = os.path.join(dirpath, filename)
                try:
                    with open(filepath, encoding="utf-8", errors="replace") as f:
                        for lineno, line in enumerate(f, 1):
                            if pattern in line:
                                matches.append(
                                    f"{filepath}:{lineno}:{line.rstrip()}"
                                )
                                if len(matches) >= _MAX_RESULTS:
                                    break
                except OSError:
                    continue
                if len(matches) >= _MAX_RESULTS:
                    break
            if len(matches) >= _MAX_RESULTS:
                break

        if not matches:
            return f"[find_callers] No callers found for '{method_name}'."

        output = "\n".join(matches)
        if len(matches) == _MAX_RESULTS:
            output += f"\n[find_callers] Results capped at {_MAX_RESULTS}; there may be more matches."
        return output

    return find_callers
