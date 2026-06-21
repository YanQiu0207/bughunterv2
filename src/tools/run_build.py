"""run_build tool: execute the configured build command in the fix workspace."""

import os
from typing import Any

from langchain_core.tools import tool

from src.tools._command_runner import run_command_in_workspace, validate_fix_id


_TIMEOUT_SECONDS = 120


def make_run_build_tool(workspace_root: str, build_command: str) -> Any:  # type: ignore[return]
    """Return a run_build tool bound to workspace_root and build_command.

    Args:
        workspace_root: Root directory for all fix workspaces (e.g. "workspace").
        build_command: Shell command to run inside the workspace directory.

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
        err = validate_fix_id(fix_id, "run_build")
        if err:
            return err

        workspace_path = os.path.join(workspace_root, "fix", fix_id)
        if not os.path.isdir(workspace_path):
            return (
                f"[run_build] Error: workspace not found for fix_id '{fix_id}'. "
                "Call apply_fix first."
            )

        return run_command_in_workspace(
            tool_tag="run_build",
            command=build_command,
            workspace_path=workspace_path,
            timeout=_TIMEOUT_SECONDS,
            success_label="Build succeeded.",
            failure_label="Build failed",
        )

    return run_build
