"""run_build tool: execute the configured build command in the fix workspace."""

import os
from collections.abc import Callable
from typing import Any

from langchain_core.tools import tool

from src.tools._command_runner import run_command_in_workspace, validate_fix_id

_TIMEOUT_SECONDS = 120


def make_run_build_tool(
    workspace_root: str,
    build_command: str,
    expected_fix_id: str | None = None,
    on_result: Callable[[str, bool], None] | None = None,
) -> Any:  # type: ignore[return]
    """Return a run_build tool bound to workspace_root and build_command.

    Args:
        workspace_root: Root directory for all fix workspaces (e.g. "workspace").
        build_command: Shell command to run inside the workspace directory.
        expected_fix_id: Optional fix_id bound to this tool instance.
        on_result: Optional callback receiving (fix_id, succeeded).

    Returns:
        A LangChain @tool function.
    """

    @tool
    def run_build(fix_id: str) -> str:
        """Run the build command in the isolated fix workspace.

        Executes the pre-configured build command with the workspace directory
        as the working directory and returns the combined stdout/stderr output.

        Args:
            fix_id: Identifier of the fix workspace (must exist; call apply_fix first).
        """
        err = validate_fix_id(fix_id, "run_build", expected_fix_id)
        if err:
            return err

        workspace_path = os.path.join(workspace_root, "fix", fix_id)
        if not os.path.isdir(workspace_path):
            return (
                f"[run_build] Error: workspace not found for fix_id '{fix_id}'. "
                "Call apply_fix first."
            )

        result = run_command_in_workspace(
            tool_tag="run_build",
            command=build_command,
            workspace_path=workspace_path,
            timeout=_TIMEOUT_SECONDS,
            success_label="Build succeeded.",
            failure_label="Build failed",
        )
        if on_result is not None:
            on_result(fix_id, result.startswith("[run_build] Build succeeded."))
        return result

    return run_build
