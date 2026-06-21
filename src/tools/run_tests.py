"""run_tests tool: execute the configured test command in the fix workspace."""

import os
from typing import Any

from langchain_core.tools import tool

from src.tools._command_runner import run_command_in_workspace, validate_fix_id


_TIMEOUT_SECONDS = 300


def make_run_tests_tool(workspace_root: str, test_command: str) -> Any:  # type: ignore[return]
    """Return a run_tests tool bound to workspace_root and test_command.

    Args:
        workspace_root: Root directory for all fix workspaces (e.g. "workspace").
        test_command: Shell command to run inside the workspace directory.

    Returns:
        A LangChain @tool function.
    """

    @tool
    def run_tests(fix_id: str) -> str:
        """Run the test command in the isolated fix workspace.

        Executes the pre-configured test command with the workspace directory
        as the working directory and returns the combined stdout/stderr output.
        Call this only after run_build succeeds.

        Args:
            fix_id: Identifier of the fix workspace (must exist; call apply_fix first).
        """
        err = validate_fix_id(fix_id, "run_tests")
        if err:
            return err

        workspace_path = os.path.join(workspace_root, "fix", fix_id)
        if not os.path.isdir(workspace_path):
            return (
                f"[run_tests] Error: workspace not found for fix_id '{fix_id}'. "
                "Call apply_fix first."
            )

        return run_command_in_workspace(
            tool_tag="run_tests",
            command=test_command,
            workspace_path=workspace_path,
            timeout=_TIMEOUT_SECONDS,
            success_label="Tests passed.",
            failure_label="Tests failed",
        )

    return run_tests
