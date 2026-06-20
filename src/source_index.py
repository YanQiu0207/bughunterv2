"""Source index: maps Java class names to absolute file paths."""

import os


class SourceIndex:
    """Index of Java source files under a Maven project directory.

    Builds a mapping from simple class name → absolute file path on first
    call to build(). Supports both simple names ('Demo') and fully-qualified
    names ('com.example.Demo'); the latter is resolved by matching the last
    dot-separated segment against the index.
    """

    def __init__(self, src_dir: str, extra_roots: list[str] | None = None) -> None:
        """Initialize with a source root and optional additional roots.

        Args:
            src_dir: Primary source directory to scan.
            extra_roots: Additional directories to scan (from config.extra_source_roots).
        """
        self._roots: list[str] = [src_dir] + (extra_roots or [])
        self._index: dict[str, str] = {}

    def build(self) -> None:
        """Scan all configured source roots and populate the class-name index."""
        self._index = {}
        for root in self._roots:
            for dirpath, _, filenames in os.walk(root):
                for filename in filenames:
                    if filename.endswith(".java"):
                        class_name = filename[:-5]  # strip ".java"
                        abs_path = os.path.abspath(os.path.join(dirpath, filename))
                        self._index[class_name] = abs_path

    def resolve(self, class_name: str) -> str | None:
        """Resolve a class name to its absolute file path.

        Supports simple names ('Demo') and fully-qualified names
        ('com.example.Demo'); the latter matches on the last segment only.

        Args:
            class_name: Simple or fully-qualified Java class name.

        Returns:
            Absolute path to the .java file, or None if not found.
        """
        if not self._index:
            return None

        # Try exact match first (simple name)
        if class_name in self._index:
            return self._index[class_name]

        # Fall back to last segment of fully-qualified name
        simple = class_name.rsplit(".", 1)[-1]
        return self._index.get(simple)
