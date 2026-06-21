"""Pure-Python patch utilities: hashing, conflict detection, edit application, diff generation."""

import difflib
import hashlib
import os
import pathlib
import tempfile
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.models import FixEdit


def _safe_join(base: str, rel: str) -> str:
    """Resolve *base*/*rel* and assert the result stays within *base*.

    Raises:
        ValueError: If *rel* is empty, absolute, or would escape *base*.
    """
    if not rel:
        raise ValueError("file path must be non-empty")
    if os.path.isabs(rel):
        raise ValueError(f"Absolute path not allowed: {rel!r}")
    base_path = pathlib.Path(base).resolve()
    target = (base_path / rel).resolve()
    try:
        target.relative_to(base_path)
    except ValueError:
        raise ValueError(f"Path traversal detected: {rel!r}")
    return str(target)


def snapshot_hashes(source_dir: str, files: list[str]) -> dict[str, str]:
    """Return a SHA-256 hash for each file in *files* relative to *source_dir*.

    Args:
        source_dir: Absolute path to the source directory.
        files: Relative paths of files to hash.

    Returns:
        Mapping of relative path → hex digest.

    Raises:
        OSError: If any file cannot be read.
    """
    hashes: dict[str, str] = {}
    for rel in files:
        abs_path = _safe_join(source_dir, rel)
        with open(abs_path, "rb") as fh:
            hashes[rel] = hashlib.sha256(fh.read()).hexdigest()
    return hashes


def detect_conflicts(old_hashes: dict[str, str], source_dir: str) -> list[str]:
    """Return the subset of files whose content changed since *old_hashes* was taken.

    Args:
        old_hashes: Mapping of relative path → hex digest from before svn update.
        source_dir: Absolute path to the source directory (post-update).

    Returns:
        List of relative paths whose hash now differs (or file is missing).
    """
    conflicts: list[str] = []
    for rel, old_digest in old_hashes.items():
        abs_path = _safe_join(source_dir, rel)
        if not os.path.exists(abs_path):
            conflicts.append(rel)
            continue
        with open(abs_path, "rb") as fh:
            new_digest = hashlib.sha256(fh.read()).hexdigest()
        if new_digest != old_digest:
            conflicts.append(rel)
    return conflicts


def apply_edits(source_dir: str, edits: list["FixEdit"]) -> None:
    """Apply line-level edits from a FixProposal directly to *source_dir*.

    Edits are applied back-to-front per file to preserve line-number semantics.
    Each file write is atomic (tempfile + os.replace).  If any write fails,
    already-written files are restored from their pre-edit content.

    Args:
        source_dir: Absolute path to the source directory.
        edits: List of FixEdit objects to apply.

    Raises:
        OSError: If a file cannot be read or written and rollback also fails.
        ValueError: If an edit's line range is invalid.
    """
    if not edits:
        return

    # Validate all paths and group by file.
    edits_by_file: dict[str, list["FixEdit"]] = {}
    for edit in edits:
        _safe_join(source_dir, edit.file)  # raises ValueError on path traversal
        edits_by_file.setdefault(edit.file, []).append(edit)

    written: dict[str, list[str]] = {}  # rel → original lines, for rollback

    try:
        for rel, file_edits in edits_by_file.items():
            abs_path = _safe_join(source_dir, rel)
            with open(abs_path, encoding="utf-8") as fh:
                lines = fh.readlines()

            orig_lines = list(lines)
            orig_len = len(lines)

            sorted_asc = sorted(file_edits, key=lambda e: e.start_line)
            for edit in sorted_asc:
                if edit.start_line < 1 or edit.end_line < edit.start_line or edit.end_line > orig_len:
                    raise ValueError(
                        f"Line range [{edit.start_line}, {edit.end_line}] is invalid "
                        f"for '{rel}' ({orig_len} lines)."
                    )

            for i in range(len(sorted_asc) - 1):
                if sorted_asc[i + 1].start_line <= sorted_asc[i].end_line:
                    raise ValueError(
                        f"Overlapping edits on '{rel}': edit ending at line "
                        f"{sorted_asc[i].end_line} overlaps with edit starting at line "
                        f"{sorted_asc[i + 1].start_line}."
                    )

            for edit in reversed(sorted_asc):
                lines[edit.start_line - 1 : edit.end_line] = (
                    edit.new_content.splitlines(keepends=True)
                )

            _atomic_write_lines(abs_path, lines)
            written[rel] = orig_lines

    except Exception:
        # Best-effort rollback of already-written files.
        for rel, orig_lines in written.items():
            try:
                _atomic_write_lines(_safe_join(source_dir, rel), orig_lines)
            except OSError:
                pass
        raise


def generate_diff(source_dir: str, workspace_dir: str, files: list[str]) -> str:
    """Return a unified diff between source_dir and workspace_dir for *files*.

    Args:
        source_dir: Absolute path to the original source directory.
        workspace_dir: Absolute path to the modified workspace directory.
        files: Relative paths of files to diff.

    Returns:
        Unified diff text (empty string if no differences).
    """
    chunks: list[str] = []
    for rel in files:
        src_path = _safe_join(source_dir, rel)
        ws_path = _safe_join(workspace_dir, rel)

        if not os.path.exists(ws_path):
            raise FileNotFoundError(
                f"Workspace file not found for '{rel}'. "
                "The workspace may be incomplete — delete it and retry."
            )
        src_lines = _read_lines(src_path)
        ws_lines = _read_lines(ws_path)

        diff = list(
            difflib.unified_diff(
                src_lines,
                ws_lines,
                fromfile=f"a/{rel}",
                tofile=f"b/{rel}",
            )
        )
        if diff:
            chunks.extend(diff)

    return "".join(chunks)


def _atomic_write_lines(path: str, lines: list[str]) -> None:
    """Write *lines* to *path* atomically via a temp file in the same directory."""
    dir_ = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.writelines(lines)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read_lines(path: str) -> list[str]:
    """Read a file as lines; return empty list if the file does not exist."""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return fh.readlines()
