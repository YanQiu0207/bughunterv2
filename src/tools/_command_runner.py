"""Internal helpers for running shell commands in fix workspaces."""

import re
import shlex
import subprocess

_MAX_OUTPUT_LINES = 200
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def validate_fix_id(fix_id: str, tool_tag: str) -> str | None:
    """Check that fix_id is a well-formed UUID.

    Args:
        fix_id: Identifier to validate.
        tool_tag: Prefix used in the error message (e.g. "run_build").

    Returns:
        An error string if invalid, or None if valid.
    """
    if not _UUID_RE.match(fix_id):
        return (
            f"[{tool_tag}] Error: fix_id '{fix_id}' is not a valid UUID. "
            "Use the fix_id provided at the start of the session."
        )
    return None


def run_command_in_workspace(
    tool_tag: str,
    command: str,
    workspace_path: str,
    timeout: int,
    success_label: str,
    failure_label: str,
) -> str:
    """Run a shell command in workspace_path and return formatted output.

    Args:
        tool_tag: Prefix string used in error/status messages (e.g. "run_build").
        command: Shell command to execute.
        workspace_path: Working directory for the subprocess.
        timeout: Maximum seconds to wait before terminating.
        success_label: Status line on exit code 0 (e.g. "Build succeeded.").
        failure_label: Status line prefix on non-zero exit (e.g. "Build failed").

    Returns:
        Human-readable result string with status header and captured output.
    """
    try:
        cmd_args = shlex.split(command)
    except ValueError as exc:
        return f"[{tool_tag}] Error: invalid command syntax: {exc}"
    try:
        proc = subprocess.run(
            cmd_args,
            cwd=workspace_path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return f"[{tool_tag}] Error: timed out after {timeout} seconds."
    except OSError as exc:
        return f"[{tool_tag}] Error: {exc}"

    output = proc.stdout + proc.stderr
    lines = output.splitlines()
    truncated = len(lines) > _MAX_OUTPUT_LINES
    display = "\n".join(lines[:_MAX_OUTPUT_LINES])
    truncation_note = (
        f"\n[{tool_tag}] Output truncated ({len(lines)} lines total)."
        if truncated
        else ""
    )

    if proc.returncode == 0:
        return f"[{tool_tag}] {success_label}\n--- output ---\n{display}{truncation_note}"
    return (
        f"[{tool_tag}] {failure_label} (exit code {proc.returncode}).\n"
        f"--- output ---\n{display}{truncation_note}"
    )
