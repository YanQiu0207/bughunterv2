"""apply_fix tool: create a hardlink workspace and apply line-level edits."""

import json
import logging
import os
import pathlib
import shutil
import tempfile
from typing import Any

from langchain_core.tools import tool

from src.tools._command_runner import validate_fix_id


_MAX_EDITS = 50
_MODIFIED_REGISTRY = ".fix_modified_files"
_REGISTRY_MAX_BYTES = 1 * 1024 * 1024       # 1 MB guard against tampered registry
_MAX_NEW_CONTENT_BYTES = 512 * 1024         # per-edit cap (512 KB)
_MAX_TOTAL_CONTENT_BYTES = 4 * 1024 * 1024  # whole-batch cap (4 MB)

logger = logging.getLogger(__name__)


def _validate_rel_path(base: str, rel: str) -> str:
    """Validate that base/rel does not escape base; return the resolved path.

    Args:
        base: Absolute base directory.
        rel: Relative path provided by the caller.

    Returns:
        Resolved absolute path of base/rel.

    Raises:
        ValueError: If rel is empty, absolute, or would escape base.
    """
    if not rel:
        raise ValueError("file must be a non-empty string")
    if os.path.isabs(rel):
        raise ValueError(f"Absolute path not allowed: {rel!r}")
    base_path = pathlib.Path(base).resolve()
    target = (base_path / rel).resolve()
    try:
        target.relative_to(base_path)
    except ValueError:
        raise ValueError(f"Path traversal detected: {rel!r}")
    return str(target)


def _load_modified_registry(workspace_path: str) -> set[str]:
    """Load the set of relative paths modified in previous apply_fix calls."""
    registry = os.path.join(workspace_path, _MODIFIED_REGISTRY)
    if not os.path.exists(registry):
        return set()
    if os.path.getsize(registry) > _REGISTRY_MAX_BYTES:
        raise RuntimeError(
            f"Registry file at '{registry}' exceeds {_REGISTRY_MAX_BYTES} bytes. "
            "The workspace may be corrupt; delete the workspace directory and retry."
        )
    with open(registry, encoding="utf-8") as fh:
        return set(json.load(fh))


def _save_modified_registry(workspace_path: str, files: set[str]) -> None:
    """Persist the set of relative paths modified so far in this workspace.

    Uses an atomic tempfile+replace pattern to avoid partial writes on crash.
    """
    registry = os.path.join(workspace_path, _MODIFIED_REGISTRY)
    fd, tmp_path = tempfile.mkstemp(dir=workspace_path, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(sorted(files), fh)
        os.replace(tmp_path, registry)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _atomic_write_lines(ws_file: str, lines: list[str]) -> None:
    """Write lines to ws_file atomically using a temp file in the same directory.

    This breaks any existing hardlink by replacing ws_file's directory entry
    with a new inode, leaving the original source inode untouched.

    Args:
        ws_file: Absolute path to the destination file in the workspace.
        lines: Content to write (as returned by readlines()).

    Raises:
        OSError: If the temp file cannot be written or replaced.
    """
    ws_dir = os.path.dirname(ws_file)
    fd, tmp_path = tempfile.mkstemp(dir=ws_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.writelines(lines)
        os.replace(tmp_path, ws_file)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def make_apply_fix_tool(
    workspace_root: str,
    target_project_dir: str,
) -> Any:  # type: ignore[return]
    """Return an apply_fix tool bound to workspace_root and target_project_dir.

    The tool creates a hardlink-based isolation workspace on first call, then
    applies line-level edits to workspace files.  The original project directory
    is never modified.

    Args:
        workspace_root: Root directory for all fix workspaces (e.g. "workspace").
        target_project_dir: Absolute path to the Java project being fixed.

    Returns:
        A LangChain @tool function.
    """

    @tool
    def apply_fix(fix_id: str, edits: list[dict[str, Any]]) -> str:
        """Apply line-level code edits to an isolated hardlink workspace.

        On the first call, creates the workspace by hardlinking all files from
        the target project (near-zero disk overhead).  On each subsequent call,
        ALL previously modified files are restored to their original content
        before the new edits are applied, ensuring the workspace exactly
        reflects the current edits list.

        Args:
            fix_id: Unique identifier for this fix; must be the UUID provided in
                the task description.
            edits: List of edit dicts.  Each dict must contain:
                - file (str): path relative to the project root (no '..' or
                  hidden-file paths allowed)
                - start_line (int): first line to replace, 1-based inclusive
                - end_line (int): last line to replace, 1-based inclusive
                - new_content (str): replacement text (must be non-empty;
                  include trailing newline)
                - reason (str): one-sentence rationale for this change
        """
        # --- fix_id validation ---
        err = validate_fix_id(fix_id, "apply_fix")
        if err:
            return err

        if len(edits) > _MAX_EDITS:
            return (
                f"[apply_fix] Error: {len(edits)} edits exceed the maximum of "
                f"{_MAX_EDITS}. Split into smaller batches."
            )

        # Compute workspace_path up-front so path validation uses the actual
        # operating directory, not the shallower workspace_root.
        workspace_path = os.path.join(workspace_root, "fix", fix_id)

        # --- validate all edits before touching the filesystem ---
        total_content_bytes = 0
        for edit in edits:
            rel = edit.get("file", "")

            # Reject hidden/metadata files (dot-prefix components) to prevent
            # the LLM from overwriting internal files like .fix_modified_files.
            if any(part.startswith(".") for part in pathlib.Path(rel).parts):
                return (
                    f"[apply_fix] Error: editing hidden/metadata files is not "
                    f"allowed: {rel!r}"
                )

            try:
                _validate_rel_path(workspace_path, rel)
                _validate_rel_path(target_project_dir, rel)
            except ValueError as exc:
                return f"[apply_fix] Error: {exc}"

            nc = edit.get("new_content", "")
            if not nc:
                return (
                    f"[apply_fix] Error: 'new_content' for edit on '{rel}' is empty. "
                    "Provide the replacement text, or at minimum a single newline."
                )
            nc_bytes = len(nc.encode())
            if nc_bytes > _MAX_NEW_CONTENT_BYTES:
                return (
                    f"[apply_fix] Error: 'new_content' for edit on '{rel}' is "
                    f"{nc_bytes} bytes, exceeding the 512 KB per-edit limit."
                )
            total_content_bytes += nc_bytes

        if total_content_bytes > _MAX_TOTAL_CONTENT_BYTES:
            return (
                f"[apply_fix] Error: total new_content size ({total_content_bytes} bytes) "
                "exceeds the 4 MB batch limit."
            )

        # --- workspace creation ---
        if not os.path.exists(workspace_path):
            try:
                shutil.copytree(
                    target_project_dir,
                    workspace_path,
                    copy_function=os.link,
                )
            except OSError as exc:
                if os.path.exists(workspace_path):
                    try:
                        shutil.rmtree(workspace_path)
                    except OSError:
                        pass
                return f"[apply_fix] Error creating workspace: {exc}"

        # --- restore ALL previously modified files ---
        # Validate each registry entry before trusting it; skip corrupt entries.
        try:
            raw_registry = _load_modified_registry(workspace_path)
        except RuntimeError as exc:
            return f"[apply_fix] Error: {exc}"
        previously_modified: set[str] = set()
        for rel_file in raw_registry:
            try:
                _validate_rel_path(workspace_path, rel_file)
                previously_modified.add(rel_file)
            except ValueError:
                logger.warning("Skipping invalid registry entry: %r", rel_file)

        for rel_file in list(previously_modified):
            ws_file = os.path.join(workspace_path, rel_file)
            orig_file = os.path.join(target_project_dir, rel_file)
            if not os.path.exists(orig_file):
                # Source file was deleted; sync workspace to match.
                if os.path.exists(ws_file):
                    try:
                        os.unlink(ws_file)
                    except OSError as exc:
                        return f"[apply_fix] Error: cannot sync deleted file '{rel_file}': {exc}"
                logger.warning(
                    "Source file '%s' no longer exists; removed workspace copy.",
                    rel_file,
                )
                previously_modified.discard(rel_file)
                continue
            try:
                if os.path.exists(ws_file):
                    os.unlink(ws_file)
                os.link(orig_file, ws_file)
            except OSError as exc:
                return f"[apply_fix] Error: could not restore '{rel_file}': {exc}"

        # --- group edits by file ---
        edits_by_file: dict[str, list[dict[str, Any]]] = {}
        for edit in edits:
            rel = edit.get("file", "")
            edits_by_file.setdefault(rel, []).append(edit)

        # Pre-check all target files exist before modifying any of them.
        for rel_file in edits_by_file:
            ws_file = os.path.join(workspace_path, rel_file)
            if not os.path.exists(ws_file):
                return (
                    f"[apply_fix] Error: file '{rel_file}' not found in workspace."
                )

        # --- read all files and validate all ranges before writing anything ---
        # A validation failure on any file must not leave other files partially
        # written but absent from the registry (which would prevent restoration).
        file_lines: dict[str, list[str]] = {}
        file_sorted_edits: dict[str, list[dict[str, Any]]] = {}

        for rel_file, file_edits in edits_by_file.items():
            ws_file = os.path.join(workspace_path, rel_file)

            with open(ws_file, encoding="utf-8") as fh:
                lines = fh.readlines()

            orig_len = len(lines)

            sorted_edits_asc = sorted(
                file_edits, key=lambda e: int(e.get("start_line", 0))
            )

            # Detect overlapping ranges.
            for i in range(len(sorted_edits_asc) - 1):
                a_end = int(sorted_edits_asc[i].get("end_line", 0))
                b_start = int(sorted_edits_asc[i + 1].get("start_line", 0))
                if b_start <= a_end:
                    return (
                        f"[apply_fix] Error: overlapping edits on '{rel_file}': "
                        f"edit ending at line {a_end} overlaps with edit starting "
                        f"at line {b_start}. Each edit must target a distinct line range."
                    )

            # Validate all line ranges.
            for edit in sorted_edits_asc:
                start = int(edit.get("start_line", 0))
                end = int(edit.get("end_line", 0))
                if start < 1 or end < start or end > orig_len:
                    return (
                        f"[apply_fix] Error: line range [{start}, {end}] is invalid "
                        f"for '{rel_file}' ({orig_len} lines total)."
                    )

            file_lines[rel_file] = lines
            file_sorted_edits[rel_file] = sorted_edits_asc

        # --- all validations passed; apply edits and write ---
        newly_modified: set[str] = set()
        for rel_file, sorted_edits_asc in file_sorted_edits.items():
            ws_file = os.path.join(workspace_path, rel_file)
            lines = file_lines[rel_file]

            for edit in reversed(sorted_edits_asc):
                start = int(edit.get("start_line", 0))
                end = int(edit.get("end_line", 0))
                new_content: str = edit.get("new_content", "")
                lines[start - 1 : end] = new_content.splitlines(keepends=True)

            _atomic_write_lines(ws_file, lines)
            newly_modified.add(rel_file)

        # Accumulate all ever-modified files so the next call can restore them.
        _save_modified_registry(workspace_path, previously_modified | newly_modified)

        files_list = "\n  ".join(sorted(newly_modified))
        return (
            f"[apply_fix] Applied {len(edits)} edit(s) to workspace/fix/{fix_id}/.\n"
            f"  Modified:\n  {files_list}"
        )

    return apply_fix
