"""Internal helpers for running shell commands in fix workspaces."""

import re
import shlex
import subprocess
from dataclasses import dataclass

_MAX_OUTPUT_LINES = 200
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CommandResult:
    """Structured command result for internal callbacks."""

    message: str
    succeeded: bool


def validate_fix_id(
    fix_id: str,
    tool_tag: str,
    expected_fix_id: str | None = None,
) -> str | None:
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
    if expected_fix_id is not None and fix_id != expected_fix_id:
        return (
            f"[{tool_tag}] Error: fix_id '{fix_id}' does not match the current "
            "session fix_id."
        )
    return None


def run_command_result_in_workspace(
    tool_tag: str,
    command: str,
    workspace_path: str,
    timeout: int,
    success_label: str,
    failure_label: str,
) -> CommandResult:
    """Run a shell command in workspace_path and return structured output.

    Args:
        tool_tag: Prefix string used in error/status messages (e.g. "run_build").
        command: Shell command to execute.
        workspace_path: Working directory for the subprocess.
        timeout: Maximum seconds to wait before terminating.
        success_label: Status line on exit code 0 (e.g. "Build succeeded.").
        failure_label: Status line prefix on non-zero exit (e.g. "Build failed").

    Returns:
        CommandResult with human-readable output and success flag.
    """
    try:
        cmd_args = shlex.split(command)
    except ValueError as exc:
        return CommandResult(
            message=f"[{tool_tag}] Error: invalid command syntax: {exc}",
            succeeded=False,
        )
    try:
        proc = subprocess.run(
            cmd_args,
            cwd=workspace_path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return CommandResult(
            message=f"[{tool_tag}] Error: timed out after {timeout} seconds.",
            succeeded=False,
        )
    except OSError as exc:
        return CommandResult(
            message=f"[{tool_tag}] Error: {exc}", succeeded=False
        )

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
        return CommandResult(
            message=(
                f"[{tool_tag}] {success_label}\n"
                f"--- output ---\n{display}{truncation_note}"
            ),
            succeeded=True,
        )
    return CommandResult(
        message=(
            f"[{tool_tag}] {failure_label} (exit code {proc.returncode}).\n"
            f"--- output ---\n{display}{truncation_note}"
        ),
        succeeded=False,
    )


def run_command_in_workspace(
    tool_tag: str,
    command: str,
    workspace_path: str,
    timeout: int,
    success_label: str,
    failure_label: str,
) -> str:
    """Run a shell command in workspace_path and return formatted output."""
    return run_command_result_in_workspace(
        tool_tag=tool_tag,
        command=command,
        workspace_path=workspace_path,
        timeout=timeout,
        success_label=success_label,
        failure_label=failure_label,
    ).message
