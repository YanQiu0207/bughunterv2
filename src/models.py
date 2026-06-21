"""Data models shared across the diagnosis and fix pipelines."""

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class StackFrame:
    """One frame from a Java exception stack trace."""

    class_name: str
    method: str
    file: str
    line: int


@dataclass
class Location:
    """Source location within a Java file."""

    file: str
    line: int
    method: str


@dataclass
class EvidenceItem:
    """A piece of evidence collected during a backtrace step."""

    type: str
    file: str
    line: int
    snippet: str


@dataclass
class BacktraceStep:
    """One iteration of the backtrace loop."""

    step: int
    suspect_variable: str
    location: Location
    decision: Literal["in_code", "out_of_code"]
    finding: str
    evidence: list[EvidenceItem] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Conclusion:
    """Final diagnosis conclusion with evidence chain."""

    root_cause_hypothesis: str
    evidence_refs: list[str]
    counter_check: str
    fix_direction: str
    confidence: Literal["high", "medium", "low"]
    confidence_reason: str


@dataclass
class DiagnosisInput:
    """Input parameters captured at the start of a diagnosis run."""

    stack_trace: str
    source_dir: str


@dataclass
class DiagnosisReport:
    """Complete diagnosis report, persisted to workspace/diagnosis/<id>.json."""

    diagnosis_id: str
    created_at: str
    status: Literal["in_progress", "completed", "paused"]
    input: DiagnosisInput
    backtrace_steps: list[BacktraceStep] = field(default_factory=list)
    conclusion: Conclusion | None = None


@dataclass
class FixEdit:
    """One line-level code edit within a fix proposal."""

    file: str
    start_line: int
    end_line: int
    new_content: str
    reason: str


@dataclass
class FixProposal:
    """A complete fix proposal generated from a DiagnosisReport.

    Persisted to workspace/fix/<proposal_id>.json.
    """

    proposal_id: str
    diagnosis_id: str
    created_at: str
    status: Literal["draft", "applied", "verified"]
    edits: list[FixEdit]
    summary: str
