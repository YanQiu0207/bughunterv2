"""DiagnosisAgent: LangGraph ReAct agent for Java bug root-cause diagnosis."""

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.runtime_noise import configure_runtime_noise_filters

configure_runtime_noise_filters()

from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from src.agent.prompts import build_system_prompt
from src.config import Config
from src.models import (
    Conclusion,
    DiagnosisInput,
    DiagnosisReport,
    StackFrame,
)
from src.source_index import SourceIndex
from src.tools.find_callers import make_find_callers_tool
from src.tools.read_source import make_read_source_tool

# Resolved at import time so relative __file__ paths don't cause surprises
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_WORKSPACE_DIR = str(_PROJECT_ROOT / "workspace" / "diagnosis")


def make_submit_diagnosis_tool(
    result_holder: dict[str, Any],
):  # type: ignore[return]
    """Return a submit_diagnosis tool that stores its result in result_holder.

    When the agent calls this tool, the structured conclusion is captured in
    result_holder so the outer run() method can read it after invoke() returns.
    Duplicate calls are ignored — the first valid submission wins.

    Args:
        result_holder: Mutable dict; populated with diagnosis fields on call.

    Returns:
        A LangChain @tool function.
    """

    @tool
    def submit_diagnosis(
        root_cause_hypothesis: str,
        evidence: list[dict[str, Any]],
        counter_check: str,
        fix_direction: str,
        confidence: str,
        confidence_reason: str,
    ) -> str:
        """Submit the final diagnosis and stop the investigation.

        Call this tool exactly once when you have determined the root cause or
        reached a stopping condition. Do not call any other tools after this.

        Args:
            root_cause_hypothesis: One falsifiable sentence stating the root cause.
            evidence: List of evidence items; each should have 'type', 'file',
                'line', and 'snippet'.
            counter_check: How alternative explanations were ruled out.
            fix_direction: High-level fix direction (not the actual code change).
            confidence: One of "high", "medium", or "low".
            confidence_reason: One sentence explaining the confidence level.
        """
        if result_holder:
            # First submission wins; ignore duplicates
            return "Diagnosis already submitted. Do not call any more tools."

        result_holder.update(
            {
                "root_cause_hypothesis": root_cause_hypothesis,
                "evidence": evidence,
                "counter_check": counter_check,
                "fix_direction": fix_direction,
                "confidence": confidence,
                "confidence_reason": confidence_reason,
            }
        )
        return (
            "Diagnosis submitted successfully. "
            "Do not call any more tools. Your work is complete."
        )

    return submit_diagnosis


class DiagnosisAgent:
    """Orchestrates a LangGraph ReAct agent to diagnose Java exceptions."""

    def __init__(
        self,
        config: Config,
        index: SourceIndex,
        src_dir: str,
    ) -> None:
        """Initialize the agent with runtime config and source index.

        Args:
            config: Loaded runtime configuration (framework packages, max_steps).
            index: Pre-built SourceIndex for class-name resolution.
            src_dir: Source root directory (used by find_callers).
        """
        self._config = config
        self._index = index
        self._src_dir = src_dir

    def run(self, stack_trace: str, frames: list[StackFrame]) -> DiagnosisReport:
        """Run the diagnosis agent on a parsed stack trace.

        Args:
            stack_trace: Raw stack trace text (stored in the report).
            frames: Parsed frames from the stack trace, topmost first.

        Returns:
            Completed DiagnosisReport with conclusion populated on success.
        """
        diagnosis_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()

        report = DiagnosisReport(
            diagnosis_id=diagnosis_id,
            created_at=created_at,
            status="in_progress",
            input=DiagnosisInput(
                stack_trace=stack_trace,
                source_dir=self._src_dir,
            ),
        )

        result_holder: dict[str, Any] = {}

        tools = [
            make_read_source_tool(self._index),
            make_find_callers_tool(self._src_dir),
            make_submit_diagnosis_tool(result_holder),
        ]

        llm = ChatOpenAI(
            model=self._config.llm_model,
            base_url=self._config.llm_base_url,
            api_key=self._config.llm_api_key,
            max_tokens=4096,
        )

        system_prompt = build_system_prompt(
            max_steps=self._config.max_steps,
            framework_packages=self._config.framework_packages,
            output_language=self._config.diagnosis_output_language,
            extra_instructions=self._config.diagnosis_prompt_append,
        )

        # LangGraph 0.2 uses messages_modifier for system prompt injection
        agent = create_react_agent(
            llm,
            tools,
            messages_modifier=system_prompt,
        )

        frames_text = "\n".join(
            f"  at {f.class_name}.{f.method}({f.file}:{f.line})"
            for f in frames
        )
        user_message = (
            f"Diagnose this Java exception:\n\n"
            f"{stack_trace}\n\n"
            f"Parsed frames (topmost first):\n{frames_text}\n\n"
            f"Source directory: {self._src_dir}"
        )

        # Each tool call involves 2 graph steps (agent + tool node); buffer included
        recursion_limit = self._config.max_steps * 4 + 10

        try:
            agent.invoke(
                {"messages": [{"role": "user", "content": user_message}]},
                config={"recursion_limit": recursion_limit},
            )
        except Exception as exc:
            # Even on error, use any valid submission captured before the error
            if not result_holder:
                report.status = "completed"
                report.conclusion = Conclusion(
                    root_cause_hypothesis=f"Agent terminated unexpectedly: {exc}",
                    evidence_refs=[],
                    counter_check="N/A — agent error",
                    fix_direction="Review agent logs for details.",
                    confidence="low",
                    confidence_reason=f"Agent error: {type(exc).__name__}",
                )
                self._checkpoint(report)
                return report
            # Fall through to normal result_holder processing below

        report.conclusion = _build_conclusion(result_holder)
        report.status = "completed"
        self._checkpoint(report)
        return report

    def _checkpoint(self, report: DiagnosisReport) -> None:
        """Write the current report state to workspace/diagnosis/<id>.json (atomic)."""
        os.makedirs(_WORKSPACE_DIR, exist_ok=True)
        target = os.path.join(_WORKSPACE_DIR, f"{report.diagnosis_id}.json")
        data = json.dumps(_report_to_dict(report), ensure_ascii=False, indent=2)
        # Write to a temp file then rename for atomic replacement
        fd, tmp_path = tempfile.mkstemp(dir=_WORKSPACE_DIR, suffix=".json.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(data)
            os.replace(tmp_path, target)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


def _build_conclusion(result_holder: dict[str, Any]) -> Conclusion:
    """Build a Conclusion from a filled result_holder dict."""
    if not result_holder:
        return Conclusion(
            root_cause_hypothesis="Agent completed without submitting a diagnosis.",
            evidence_refs=[],
            counter_check="",
            fix_direction="",
            confidence="low",
            confidence_reason="submit_diagnosis was not called.",
        )

    confidence = result_holder.get("confidence", "low")
    if confidence not in ("high", "medium", "low"):
        confidence = "low"

    evidence_refs = [
        _evidence_to_ref(e) for e in result_holder.get("evidence", [])
    ]
    return Conclusion(
        root_cause_hypothesis=result_holder.get("root_cause_hypothesis", "Unknown"),
        evidence_refs=evidence_refs,
        counter_check=result_holder.get("counter_check", ""),
        fix_direction=result_holder.get("fix_direction", ""),
        confidence=confidence,  # type: ignore[arg-type]
        confidence_reason=result_holder.get("confidence_reason", ""),
    )


def _evidence_to_ref(e: Any) -> str:
    """Convert an evidence item (dict or str) to a reference string."""
    if isinstance(e, dict):
        file_ = e.get("file", "")
        raw_line = e.get("line", "")
        try:
            line_ = int(raw_line) if raw_line not in ("", None) else 0
        except (TypeError, ValueError):
            line_ = 0
        snippet = e.get("snippet", "")
        return f"{file_}:{line_} — {snippet}"
    return str(e)


def _report_to_dict(report: DiagnosisReport) -> dict[str, Any]:
    """Serialize a DiagnosisReport to a JSON-compatible dict."""
    conclusion = None
    if report.conclusion:
        c = report.conclusion
        conclusion = {
            "root_cause_hypothesis": c.root_cause_hypothesis,
            "evidence_refs": c.evidence_refs,
            "counter_check": c.counter_check,
            "fix_direction": c.fix_direction,
            "confidence": c.confidence,
            "confidence_reason": c.confidence_reason,
        }

    return {
        "diagnosis_id": report.diagnosis_id,
        "created_at": report.created_at,
        "status": report.status,
        "input": {
            "stack_trace": report.input.stack_trace,
            "source_dir": report.input.source_dir,
        },
        "backtrace_steps": [
            {
                "step": s.step,
                "suspect_variable": s.suspect_variable,
                "location": {
                    "file": s.location.file,
                    "line": s.location.line,
                    "method": s.location.method,
                },
                "decision": s.decision,
                "finding": s.finding,
                "evidence": [
                    {
                        "type": e.type,
                        "file": e.file,
                        "line": e.line,
                        "snippet": e.snippet,
                    }
                    for e in s.evidence
                ],
                "tool_calls": s.tool_calls,
            }
            for s in report.backtrace_steps
        ],
        "conclusion": conclusion,
    }
