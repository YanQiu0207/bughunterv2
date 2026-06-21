"""Integration test: canonical NPE example end-to-end diagnosis.

Requires a real LLM_API_KEY environment variable and config.yaml model settings.
Run with: pytest tests/test_integration.py -v -m integration
"""

import json
from pathlib import Path

import pytest

from src.agent.diagnosis_agent import DiagnosisAgent
from src.config import load_config
from src.source_index import SourceIndex
from src.stack_parser import parse_stack_trace

_PROJECT_ROOT = Path(__file__).parent.parent
_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_STACK_TRACE_FILE = _FIXTURES_DIR / "stack_trace.txt"
_SRC_DIR = str(_FIXTURES_DIR / "src")
_CONFIG_FILE = _PROJECT_ROOT / "config.yaml"


@pytest.fixture(scope="module")
def stack_text() -> str:
    return _STACK_TRACE_FILE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def diagnosis_report(stack_text: str):
    """Run the full diagnosis pipeline once and return the report."""
    config = load_config(str(_CONFIG_FILE))
    if not config.llm_api_key:
        pytest.skip("LLM_API_KEY is required for integration diagnosis tests.")

    index = SourceIndex(_SRC_DIR)
    index.build()

    frames = parse_stack_trace(stack_text)
    agent = DiagnosisAgent(config=config, index=index, src_dir=_SRC_DIR)
    return agent.run(stack_trace=stack_text, frames=frames)


@pytest.mark.integration
def test_conclusion_not_none(diagnosis_report):
    """Agent must submit a diagnosis."""
    assert diagnosis_report.conclusion is not None, (
        "DiagnosisAgent.run() returned a report with conclusion=None"
    )


@pytest.mark.integration
def test_conclusion_confidence(diagnosis_report):
    """Confidence must be 'high' for a canonical, fully traceable NPE."""
    assert diagnosis_report.conclusion is not None
    assert diagnosis_report.conclusion.confidence == "high", (
        f"Expected confidence='high', got {diagnosis_report.conclusion.confidence!r}"
    )


@pytest.mark.integration
def test_root_cause_mentions_null_or_handle(diagnosis_report):
    """Root-cause hypothesis must mention the NPE trigger."""
    assert diagnosis_report.conclusion is not None
    hypothesis = diagnosis_report.conclusion.root_cause_hypothesis.lower()
    assert "null" in hypothesis or "handle" in hypothesis, (
        f"Root cause hypothesis does not mention 'null' or 'handle': {hypothesis!r}"
    )


@pytest.mark.integration
def test_fix_direction_non_empty(diagnosis_report):
    """Fix direction must be populated."""
    assert diagnosis_report.conclusion is not None
    assert diagnosis_report.conclusion.fix_direction.strip(), (
        "fix_direction is empty"
    )


@pytest.mark.integration
def test_report_status_completed(diagnosis_report):
    assert diagnosis_report.status == "completed"


@pytest.mark.integration
def test_json_checkpoint_exists_and_valid(diagnosis_report):
    """Atomic checkpoint written by DiagnosisAgent must exist and be valid JSON."""
    workspace = Path(__file__).parent.parent / "workspace" / "diagnosis"
    json_path = workspace / f"{diagnosis_report.diagnosis_id}.json"

    assert json_path.exists(), f"Checkpoint file not found: {json_path}"

    with json_path.open(encoding="utf-8") as f:
        data = json.load(f)

    # spec §4.8 required top-level keys
    for key in ("diagnosis_id", "status", "backtrace_steps", "conclusion"):
        assert key in data, f"Missing key {key!r} in checkpoint JSON"

    assert data["diagnosis_id"] == diagnosis_report.diagnosis_id
    assert data["status"] == "completed"
    assert data["conclusion"] is not None
