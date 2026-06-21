"""Thin wrappers around SVN command-line operations."""

import re
import subprocess


def svn_update(path: str) -> None:
    """Run 'svn update' in the given working copy directory.

    Args:
        path: Absolute path to the SVN working copy root.

    Raises:
        RuntimeError: If the svn command exits with a non-zero status.
    """
    result = subprocess.run(
        ["svn", "update"],
        cwd=path,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"svn update failed (exit {result.returncode}):\n{result.stderr.strip()}"
        )


def svn_commit(path: str, message: str, files: list[str]) -> str:
    """Run 'svn commit' on the specified files in the given working copy directory.

    Args:
        path: Absolute path to the SVN working copy root.
        message: Commit log message.
        files: Relative paths (under *path*) to include in this commit.

    Returns:
        The committed revision number as a string (e.g. "42"), or "?" if the
        revision could not be parsed from SVN output.

    Raises:
        RuntimeError: If the svn command exits with a non-zero status.
    """
    result = subprocess.run(
        ["svn", "commit", "--message", message, "--"] + files,
        cwd=path,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"svn commit failed (exit {result.returncode}):\n{result.stderr.strip()}"
        )
    match = re.search(r"Committed revision (\d+)\.", result.stdout)
    return match.group(1) if match else "?"


def svn_dirty_files(path: str, files: list[str]) -> list[str]:
    """Return which of the given files have local modifications in the SVN working copy.

    Args:
        path: Absolute path to the SVN working copy root.
        files: Relative file paths to check.

    Returns:
        Subset of *files* that have any local modification (modified, added,
        deleted, conflicted, etc.).  Clean and unversioned files are excluded.

    Raises:
        RuntimeError: If the svn command exits with a non-zero status.
    """
    if not files:
        return []
    result = subprocess.run(
        ["svn", "status", "--"] + files,
        cwd=path,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"svn status failed (exit {result.returncode}):\n{result.stderr.strip()}"
        )
    dirty = []
    for line in result.stdout.splitlines():
        if not line or line[0] in (" ", "?"):
            continue
        # Standard svn status output: 8 status/flag columns, then the path.
        if len(line) > 8:
            dirty.append(line[8:].strip())
    return dirty


def svn_revert(path: str, files: list[str]) -> None:
    """Run 'svn revert' on the specified files.

    Args:
        path: Absolute path to the SVN working copy root.
        files: List of paths relative to *path* to revert.

    Raises:
        RuntimeError: If the svn command exits with a non-zero status.
    """
    if not files:
        return
    result = subprocess.run(
        ["svn", "revert", "--"] + files,
        cwd=path,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"svn revert failed (exit {result.returncode}):\n{result.stderr.strip()}"
        )
