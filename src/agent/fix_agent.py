"""FixAgent: LangGraph ReAct agent for Java bug fix generation and verification."""

import json
import logging
import os
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from src.agent.fix_prompts import build_fix_system_prompt
from src.config import Config
from src.models import DiagnosisReport, FixEdit, FixProposal
from src.tools.apply_fix import make_apply_fix_tool
from src.tools.run_build import make_run_build_tool
from src.tools.run_tests import make_run_tests_tool

logger = logging.getLogger(__name__)


def make_submit_fix_proposal_tool(
    result_holder: dict[str, Any],
) -> Any:  # type: ignore[return]
    """Return a submit_fix_proposal tool that stores its result in result_holder.

    First-call-wins semantics: duplicate submissions are silently ignored.

    Args:
        result_holder: Mutable dict populated with fix proposal fields on call.

    Returns:
        A LangChain @tool function.
    """

    @tool
    def submit_fix_proposal(
        edits: list[dict[str, Any]],
        summary: str,
        status: str,
    ) -> str:
        """Submit the final fix proposal and stop.

        Call this exactly once:
        - After both run_build and run_tests succeed → status='verified'
        - When the step budget is exhausted → status='draft'

        Do not call any other tools after this.

        Args:
            edits: Final list of applied edits.  Each dict must contain
                'file', 'start_line', 'end_line', 'new_content', 'reason'.
            summary: One paragraph describing the overall fix and rationale.
            status: Either 'verified' (build+tests passed) or 'draft'
                (best effort, not fully verified).
        """
        if result_holder:
            return "Fix proposal already submitted. Do not call any more tools."

        result_holder.update(
            {
                "edits": edits,
                "summary": summary,
                "status": status,
            }
        )
        return (
            "Fix proposal submitted successfully. "
            "Do not call any more tools. Your work is complete."
        )

    return submit_fix_proposal


class FixAgent:
    """Orchestrates a LangGraph ReAct agent to generate and verify a Java fix."""

    def __init__(self, config: Config, workspace_root: str) -> None:
        """Initialise the agent with runtime config and workspace location.

        Args:
            config: Loaded runtime configuration.  Must have target_project_dir,
                build_command, and test_command populated.
            workspace_root: Directory under which fix workspaces are created
                (e.g. "workspace"; the agent writes to workspace/fix/<id>/).
        """
        self._config = config
        self._workspace_root = workspace_root

    def run(self, report: DiagnosisReport) -> FixProposal:
        """Run the fix agent on a DiagnosisReport.

        Args:
            report: Completed DiagnosisReport from M1 diagnosis.

        Returns:
            FixProposal with status 'verified' if build+tests passed, or
            'draft' if the step budget was exhausted or an error occurred.
        """
        proposal_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        diagnosis_id = report.diagnosis_id

        result_holder: dict[str, Any] = {}

        tools = [
            make_apply_fix_tool(self._workspace_root, self._config.target_project_dir),
            make_run_build_tool(self._workspace_root, self._config.build_command),
            make_run_tests_tool(self._workspace_root, self._config.test_command),
            make_submit_fix_proposal_tool(result_holder),
        ]

        llm = ChatOpenAI(
            model=self._config.llm_model,
            base_url=self._config.llm_base_url,
            api_key=self._config.llm_api_key,
            max_tokens=4096,
        )

        system_prompt = build_fix_system_prompt(max_steps=self._config.max_steps)

        agent = create_react_agent(llm, tools, prompt=system_prompt)

        user_message = _build_user_message(report, proposal_id, self._config.target_project_dir)
        recursion_limit = self._config.max_steps * 4 + 10

        try:
            agent.invoke(
                {"messages": [{"role": "user", "content": user_message}]},
                config={"recursion_limit": recursion_limit},
            )
        except Exception as exc:
            if not result_holder:
                proposal = FixProposal(
                    proposal_id=proposal_id,
                    diagnosis_id=diagnosis_id,
                    created_at=created_at,
                    status="draft",
                    edits=[],
                    summary=f"Agent terminated unexpectedly: {exc}",
                )
                self._checkpoint(proposal)
                return proposal
            # submit_fix_proposal was called before the exception; use its result.
            logger.exception(
                "Agent raised %s after submitting proposal '%s'; continuing with submitted result.",
                type(exc).__name__,
                proposal_id,
            )

        proposal = _build_fix_proposal(result_holder, proposal_id, diagnosis_id, created_at)
        self._checkpoint(proposal)
        return proposal

    def _checkpoint(self, proposal: FixProposal) -> None:
        """Write the proposal to workspace/fix/<proposal_id>.json atomically."""
        fix_dir = os.path.join(self._workspace_root, "fix")
        os.makedirs(fix_dir, exist_ok=True)
        target = os.path.join(fix_dir, f"{proposal.proposal_id}.json")
        data = json.dumps(_proposal_to_dict(proposal), ensure_ascii=False, indent=2)
        fd, tmp_path = tempfile.mkstemp(dir=fix_dir, suffix=".json.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(data)
            os.replace(tmp_path, target)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


def _build_user_message(
    report: DiagnosisReport,
    proposal_id: str,
    target_project_dir: str,
) -> str:
    """Compose the user message sent to the fix agent."""
    conclusion = report.conclusion
    if conclusion is None:
        diagnosis_text = "No diagnosis conclusion available."
    else:
        evidence_summary = "; ".join(conclusion.evidence_refs[:5]) or "none"
        diagnosis_text = (
            f"Root cause: {conclusion.root_cause_hypothesis}\n"
            f"Fix direction: {conclusion.fix_direction}\n"
            f"Confidence: {conclusion.confidence} — {conclusion.confidence_reason}\n"
            f"Evidence: {evidence_summary}"
        )

    return (
        f"Fix this Java bug based on the diagnosis below.\n\n"
        f"Diagnosis ID : {report.diagnosis_id}\n"
        f"Fix ID       : {proposal_id}\n"
        f"Project dir  : {target_project_dir}\n\n"
        f"--- Diagnosis ---\n{diagnosis_text}\n\n"
        f"Use fix_id='{proposal_id}' in all tool calls."
    )


def _build_fix_proposal(
    result_holder: dict[str, Any],
    proposal_id: str,
    diagnosis_id: str,
    created_at: str,
) -> FixProposal:
    """Construct a FixProposal from a populated (or empty) result_holder."""
    if not result_holder:
        return FixProposal(
            proposal_id=proposal_id,
            diagnosis_id=diagnosis_id,
            created_at=created_at,
            status="draft",
            edits=[],
            summary="Agent completed without submitting a fix proposal.",
        )

    raw_status = result_holder.get("status", "draft")
    status: Any = raw_status if raw_status in ("draft", "applied", "verified") else "draft"

    edits = [
        FixEdit(
            file=str(e.get("file", "")),
            start_line=int(e.get("start_line", 0)),
            end_line=int(e.get("end_line", 0)),
            new_content=str(e.get("new_content", "")),
            reason=str(e.get("reason", "")),
        )
        for e in result_holder.get("edits", [])
        if isinstance(e, dict)
    ]

    return FixProposal(
        proposal_id=proposal_id,
        diagnosis_id=diagnosis_id,
        created_at=created_at,
        status=status,
        edits=edits,
        summary=str(result_holder.get("summary", "")),
    )


def _proposal_to_dict(proposal: FixProposal) -> dict[str, Any]:
    """Serialize a FixProposal to a JSON-compatible dict."""
    return {
        "proposal_id": proposal.proposal_id,
        "diagnosis_id": proposal.diagnosis_id,
        "created_at": proposal.created_at,
        "status": proposal.status,
        "summary": proposal.summary,
        "edits": [
            {
                "file": e.file,
                "start_line": e.start_line,
                "end_line": e.end_line,
                "new_content": e.new_content,
                "reason": e.reason,
            }
            for e in proposal.edits
        ],
    }
