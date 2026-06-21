"""Unit tests for FixAgent structure and fallback behaviour."""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.agent.fix_agent import (
    FixAgent,
    _build_fix_proposal,
    _build_user_message,
    _hash_edits,
    make_submit_fix_proposal_tool,
)
from src.config import Config
from src.models import (
    Conclusion,
    DiagnosisInput,
    DiagnosisReport,
    FixEdit,
    FixProposal,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_report(
    diagnosis_id: str = "diag-001",
    fix_direction: str = "Add null check",
    with_conclusion: bool = True,
) -> DiagnosisReport:
    conclusion = (
        Conclusion(
            root_cause_hypothesis="name is null",
            evidence_refs=["Foo.java:10 — name.length()"],
            counter_check="no other null assignment found",
            fix_direction=fix_direction,
            confidence="high",
            confidence_reason="direct evidence",
        )
        if with_conclusion
        else None
    )
    return DiagnosisReport(
        diagnosis_id=diagnosis_id,
        created_at="2026-06-21T00:00:00+00:00",
        status="completed",
        input=DiagnosisInput(stack_trace="NPE at Foo:10", source_dir="/src"),
        conclusion=conclusion,
    )


def _make_config(tmp_path) -> Config:
    return Config(
        target_project_dir=str(tmp_path / "project"),
        svn_cache_dir=str(tmp_path / "svn-clean"),
        build_command="echo build ok",
        test_command="echo test ok",
    )


# ---------------------------------------------------------------------------
# make_submit_fix_proposal_tool
# ---------------------------------------------------------------------------


class TestSubmitFixProposalTool:
    def test_first_submission_populates_holder(self):
        holder: dict = {}
        tool = make_submit_fix_proposal_tool(holder)
        result = tool.invoke(
            {
                "edits": [
                    {
                        "file": "A.java",
                        "start_line": 1,
                        "end_line": 1,
                        "new_content": "x\n",
                        "reason": "r",
                    }
                ],
                "summary": "fixed it",
                "status": "verified",
            }
        )
        assert "submitted successfully" in result
        assert holder["status"] == "verified"
        assert holder["summary"] == "fixed it"
        assert len(holder["edits"]) == 1

    def test_second_submission_ignored(self):
        holder: dict = {}
        tool = make_submit_fix_proposal_tool(holder)
        tool.invoke({"edits": [], "summary": "first", "status": "verified"})
        result = tool.invoke(
            {"edits": [], "summary": "second", "status": "draft"}
        )
        assert "already submitted" in result
        assert holder["summary"] == "first"

    def test_verified_submission_downgraded_without_tool_proof(self):
        holder: dict = {}
        state = {
            "applied_hash": "hash",
            "build_hash": "hash",
            "tests_hash": None,
        }
        tool = make_submit_fix_proposal_tool(holder, state)

        result = tool.invoke(
            {
                "edits": [],
                "summary": "claims verified",
                "status": "verified",
            }
        )

        assert "submitted successfully" in result
        assert holder["status"] == "draft"
        assert "Downgraded to draft" in holder["summary"]

    def test_verified_submission_allowed_with_tool_proof(self):
        holder: dict = {}
        edits = [
            {
                "file": "A.java",
                "start_line": 1,
                "end_line": 1,
                "new_content": "x\n",
                "reason": "r",
            }
        ]
        edit_hash = _hash_edits(edits)
        state = {
            "applied_hash": edit_hash,
            "build_hash": edit_hash,
            "tests_hash": edit_hash,
        }
        tool = make_submit_fix_proposal_tool(holder, state)

        tool.invoke(
            {
                "edits": edits,
                "summary": "verified",
                "status": "verified",
            }
        )

        assert holder["status"] == "verified"


# ---------------------------------------------------------------------------
# _build_fix_proposal
# ---------------------------------------------------------------------------


class TestBuildFixProposal:
    def test_empty_holder_returns_draft(self):
        proposal = _build_fix_proposal(
            {}, "pid", "did", "2026-01-01T00:00:00+00:00"
        )
        assert isinstance(proposal, FixProposal)
        assert proposal.status == "draft"
        assert proposal.edits == []
        assert "without submitting" in proposal.summary

    def test_verified_holder_builds_correct_proposal(self):
        holder = {
            "edits": [
                {
                    "file": "Foo.java",
                    "start_line": 5,
                    "end_line": 5,
                    "new_content": "if (x == null) return;\n",
                    "reason": "null guard",
                }
            ],
            "summary": "Added null guard",
            "status": "verified",
        }
        proposal = _build_fix_proposal(
            holder, "pid", "did", "2026-01-01T00:00:00+00:00"
        )
        assert proposal.status == "verified"
        assert len(proposal.edits) == 1
        assert proposal.edits[0].file == "Foo.java"
        assert proposal.edits[0].start_line == 5
        assert proposal.summary == "Added null guard"

    def test_unknown_status_defaults_to_draft(self):
        holder = {"edits": [], "summary": "s", "status": "bad_value"}
        proposal = _build_fix_proposal(
            holder, "pid", "did", "2026-01-01T00:00:00+00:00"
        )
        assert proposal.status == "draft"

    def test_non_dict_edits_are_skipped(self):
        holder = {
            "edits": [
                {
                    "file": "A.java",
                    "start_line": 1,
                    "end_line": 1,
                    "new_content": "x\n",
                    "reason": "r",
                },
                "bad",
            ],
            "summary": "s",
            "status": "verified",
        }
        proposal = _build_fix_proposal(
            holder, "pid", "did", "2026-01-01T00:00:00+00:00"
        )
        assert len(proposal.edits) == 1


# ---------------------------------------------------------------------------
# _build_user_message
# ---------------------------------------------------------------------------


class TestBuildUserMessage:
    def test_with_conclusion_includes_fix_direction(self):
        report = _make_report(
            fix_direction="Add null guard before name.length()"
        )
        msg = _build_user_message(
            report, "pid-123", "/src/project", "/cache/svn-clean"
        )
        assert "Add null guard" in msg
        assert "pid-123" in msg
        assert "/src/project" in msg
        assert "/cache/svn-clean" in msg

    def test_without_conclusion_uses_fallback_text(self):
        report = _make_report(with_conclusion=False)
        msg = _build_user_message(
            report, "pid-456", "/src/project", "/cache/svn-clean"
        )
        assert "No diagnosis conclusion available" in msg
        assert "pid-456" in msg


# ---------------------------------------------------------------------------
# FixAgent structure
# ---------------------------------------------------------------------------


class TestFixAgentStructure:
    """Verify FixAgent registers the expected tools without calling the LLM."""

    def test_four_tools_registered(self, tmp_path):
        config = _make_config(tmp_path)
        agent = FixAgent(config=config, workspace_root=str(tmp_path / "ws"))

        captured_tools: list = []

        def fake_create_react_agent(llm, tools, **kwargs):
            captured_tools.extend(tools)
            mock_agent = MagicMock()
            mock_agent.invoke.return_value = {"messages": []}
            return mock_agent

        with (
            patch("src.agent.fix_agent.ChatOpenAI"),
            patch(
                "src.agent.fix_agent.create_react_agent",
                side_effect=fake_create_react_agent,
            ),
        ):
            agent.run(_make_report())

        tool_names = {t.name for t in captured_tools}
        assert "apply_fix" in tool_names
        assert "run_build" in tool_names
        assert "run_tests" in tool_names
        assert "submit_fix_proposal" in tool_names

    def test_apply_fix_uses_svn_cache_dir(self, tmp_path):
        config = _make_config(tmp_path)
        ws_root = tmp_path / "ws"
        agent = FixAgent(config=config, workspace_root=str(ws_root))

        fake_apply_fix = MagicMock()
        fake_apply_fix.name = "apply_fix"

        def fake_create_react_agent(llm, tools, **kwargs):
            mock_agent = MagicMock()
            mock_agent.invoke.return_value = {"messages": []}
            return mock_agent

        with (
            patch("src.agent.fix_agent.ChatOpenAI"),
            patch(
                "src.agent.fix_agent.make_apply_fix_tool",
                return_value=fake_apply_fix,
            ) as mock_apply_fix,
            patch(
                "src.agent.fix_agent.create_react_agent",
                side_effect=fake_create_react_agent,
            ),
        ):
            agent.run(_make_report())

        _, kwargs = mock_apply_fix.call_args
        assert mock_apply_fix.call_args.args[:2] == (
            str(ws_root),
            config.svn_cache_dir,
        )
        assert kwargs["expected_fix_id"]
        assert callable(kwargs["on_success"])

    def test_empty_result_holder_returns_draft(self, tmp_path):
        config = _make_config(tmp_path)
        agent = FixAgent(config=config, workspace_root=str(tmp_path / "ws"))

        def fake_create_react_agent(llm, tools, **kwargs):
            mock_agent = MagicMock()
            mock_agent.invoke.return_value = {"messages": []}
            return mock_agent

        with (
            patch("src.agent.fix_agent.ChatOpenAI"),
            patch(
                "src.agent.fix_agent.create_react_agent",
                side_effect=fake_create_react_agent,
            ),
        ):
            proposal = agent.run(_make_report())

        assert isinstance(proposal, FixProposal)
        assert proposal.status == "draft"
        assert proposal.diagnosis_id == "diag-001"

    def test_checkpoint_written_with_correct_content(self, tmp_path):
        config = _make_config(tmp_path)
        ws_root = tmp_path / "ws"
        agent = FixAgent(config=config, workspace_root=str(ws_root))

        with (
            patch("src.agent.fix_agent.ChatOpenAI"),
            patch("src.agent.fix_agent.create_react_agent") as mock_cra,
        ):
            mock_agent = MagicMock()
            mock_agent.invoke.return_value = {"messages": []}
            mock_cra.return_value = mock_agent
            proposal = agent.run(_make_report())

        json_path = ws_root / "fix" / f"{proposal.proposal_id}.json"
        assert json_path.exists(), "Checkpoint file must be written"

        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert data["proposal_id"] == proposal.proposal_id
        assert data["diagnosis_id"] == "diag-001"
        assert data["status"] == "draft"
        assert isinstance(data["edits"], list)

    def test_agent_exception_returns_draft_proposal(self, tmp_path):
        config = _make_config(tmp_path)
        ws_root = tmp_path / "ws"
        agent = FixAgent(config=config, workspace_root=str(ws_root))

        def crashing_agent(llm, tools, **kwargs):
            mock_agent = MagicMock()
            mock_agent.invoke.side_effect = RuntimeError("simulated crash")
            return mock_agent

        with (
            patch("src.agent.fix_agent.ChatOpenAI"),
            patch(
                "src.agent.fix_agent.create_react_agent",
                side_effect=crashing_agent,
            ),
        ):
            proposal = agent.run(_make_report())

        assert proposal.status == "draft"
        assert "terminated unexpectedly" in proposal.summary
        json_path = ws_root / "fix" / f"{proposal.proposal_id}.json"
        assert json_path.exists()

    def test_exception_after_unverified_submit_uses_downgraded_result(
        self, tmp_path
    ):
        config = _make_config(tmp_path)
        ws_root = tmp_path / "ws"
        agent = FixAgent(config=config, workspace_root=str(ws_root))

        submit_tool_ref: list = []

        def agent_submits_then_crashes(llm, tools, **kwargs):
            for t in tools:
                if t.name == "submit_fix_proposal":
                    submit_tool_ref.append(t)

            mock_agent = MagicMock()

            def invoke_side_effect(inputs, **kw):
                submit_tool_ref[0].invoke(
                    {
                        "edits": [
                            {
                                "file": "Foo.java",
                                "start_line": 1,
                                "end_line": 1,
                                "new_content": "fixed\n",
                                "reason": "null guard",
                            }
                        ],
                        "summary": "Added null guard",
                        "status": "verified",
                    }
                )
                raise RuntimeError("crash after submit")

            mock_agent.invoke.side_effect = invoke_side_effect
            return mock_agent

        with (
            patch("src.agent.fix_agent.ChatOpenAI"),
            patch(
                "src.agent.fix_agent.create_react_agent",
                side_effect=agent_submits_then_crashes,
            ),
        ):
            proposal = agent.run(_make_report())

        assert proposal.status == "draft"
        assert "Downgraded to draft" in proposal.summary
        json_path = ws_root / "fix" / f"{proposal.proposal_id}.json"
        assert json_path.exists()
        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert data["status"] == "draft"

    def test_verified_edits_mismatch_downgrades_to_draft(self, tmp_path):
        config = _make_config(tmp_path)
        ws_root = tmp_path / "ws"
        agent = FixAgent(config=config, workspace_root=str(ws_root))

        callbacks: dict = {}

        def fake_apply_tool(*args, **kwargs):
            callbacks["expected_fix_id"] = kwargs["expected_fix_id"]
            callbacks["apply"] = kwargs["on_success"]
            fake_tool = MagicMock()
            fake_tool.name = "apply_fix"
            return fake_tool

        def fake_build_tool(*args, **kwargs):
            callbacks["build"] = kwargs["on_result"]
            fake_tool = MagicMock()
            fake_tool.name = "run_build"
            return fake_tool

        def fake_tests_tool(*args, **kwargs):
            callbacks["tests"] = kwargs["on_result"]
            fake_tool = MagicMock()
            fake_tool.name = "run_tests"
            return fake_tool

        applied_edits = [
            {
                "file": "Foo.java",
                "start_line": 1,
                "end_line": 1,
                "new_content": "applied\n",
                "reason": "r",
            }
        ]
        submitted_edits = [
            {
                "file": "Foo.java",
                "start_line": 1,
                "end_line": 1,
                "new_content": "different\n",
                "reason": "r",
            }
        ]

        def fake_create_react_agent(llm, tools, **kwargs):
            submit_tool = next(
                t for t in tools if t.name == "submit_fix_proposal"
            )
            mock_agent = MagicMock()

            def invoke_side_effect(inputs, **kw):
                fix_id = callbacks["expected_fix_id"]
                callbacks["apply"](fix_id, applied_edits)
                callbacks["build"](fix_id, True)
                callbacks["tests"](fix_id, True)
                submit_tool.invoke(
                    {
                        "edits": submitted_edits,
                        "summary": "claims verified",
                        "status": "verified",
                    }
                )

            mock_agent.invoke.side_effect = invoke_side_effect
            return mock_agent

        with (
            patch("src.agent.fix_agent.ChatOpenAI"),
            patch(
                "src.agent.fix_agent.make_apply_fix_tool",
                side_effect=fake_apply_tool,
            ),
            patch(
                "src.agent.fix_agent.make_run_build_tool",
                side_effect=fake_build_tool,
            ),
            patch(
                "src.agent.fix_agent.make_run_tests_tool",
                side_effect=fake_tests_tool,
            ),
            patch(
                "src.agent.fix_agent.create_react_agent",
                side_effect=fake_create_react_agent,
            ),
        ):
            proposal = agent.run(_make_report())

        assert proposal.status == "draft"
        assert "Downgraded to draft" in proposal.summary

    def test_verified_edits_match_stays_verified(self, tmp_path):
        config = _make_config(tmp_path)
        ws_root = tmp_path / "ws"
        agent = FixAgent(config=config, workspace_root=str(ws_root))

        callbacks: dict = {}

        def fake_apply_tool(*args, **kwargs):
            callbacks["expected_fix_id"] = kwargs["expected_fix_id"]
            callbacks["apply"] = kwargs["on_success"]
            fake_tool = MagicMock()
            fake_tool.name = "apply_fix"
            return fake_tool

        def fake_build_tool(*args, **kwargs):
            callbacks["build"] = kwargs["on_result"]
            fake_tool = MagicMock()
            fake_tool.name = "run_build"
            return fake_tool

        def fake_tests_tool(*args, **kwargs):
            callbacks["tests"] = kwargs["on_result"]
            fake_tool = MagicMock()
            fake_tool.name = "run_tests"
            return fake_tool

        edits = [
            {
                "file": "Foo.java",
                "start_line": 1,
                "end_line": 1,
                "new_content": "applied\n",
                "reason": "r",
            }
        ]

        def fake_create_react_agent(llm, tools, **kwargs):
            submit_tool = next(
                t for t in tools if t.name == "submit_fix_proposal"
            )
            mock_agent = MagicMock()

            def invoke_side_effect(inputs, **kw):
                fix_id = callbacks["expected_fix_id"]
                callbacks["apply"](fix_id, edits)
                callbacks["build"](fix_id, True)
                callbacks["tests"](fix_id, True)
                submit_tool.invoke(
                    {
                        "edits": edits,
                        "summary": "verified",
                        "status": "verified",
                    }
                )

            mock_agent.invoke.side_effect = invoke_side_effect
            return mock_agent

        with (
            patch("src.agent.fix_agent.ChatOpenAI"),
            patch(
                "src.agent.fix_agent.make_apply_fix_tool",
                side_effect=fake_apply_tool,
            ),
            patch(
                "src.agent.fix_agent.make_run_build_tool",
                side_effect=fake_build_tool,
            ),
            patch(
                "src.agent.fix_agent.make_run_tests_tool",
                side_effect=fake_tests_tool,
            ),
            patch(
                "src.agent.fix_agent.create_react_agent",
                side_effect=fake_create_react_agent,
            ),
        ):
            proposal = agent.run(_make_report())

        assert proposal.status == "verified"
        assert proposal.edits[0].new_content == "applied\n"

    def test_failed_apply_clears_previous_verification(self, tmp_path):
        config = _make_config(tmp_path)
        ws_root = tmp_path / "ws"
        agent = FixAgent(config=config, workspace_root=str(ws_root))

        callbacks: dict = {}

        def fake_apply_tool(*args, **kwargs):
            callbacks["expected_fix_id"] = kwargs["expected_fix_id"]
            callbacks["apply_success"] = kwargs["on_success"]
            callbacks["apply_failure"] = kwargs["on_failure"]
            fake_tool = MagicMock()
            fake_tool.name = "apply_fix"
            return fake_tool

        def fake_build_tool(*args, **kwargs):
            callbacks["build"] = kwargs["on_result"]
            fake_tool = MagicMock()
            fake_tool.name = "run_build"
            return fake_tool

        def fake_tests_tool(*args, **kwargs):
            callbacks["tests"] = kwargs["on_result"]
            fake_tool = MagicMock()
            fake_tool.name = "run_tests"
            return fake_tool

        edits = [
            {
                "file": "Foo.java",
                "start_line": 1,
                "end_line": 1,
                "new_content": "applied\n",
                "reason": "r",
            }
        ]

        def fake_create_react_agent(llm, tools, **kwargs):
            submit_tool = next(
                t for t in tools if t.name == "submit_fix_proposal"
            )
            mock_agent = MagicMock()

            def invoke_side_effect(inputs, **kw):
                fix_id = callbacks["expected_fix_id"]
                callbacks["apply_success"](fix_id, edits)
                callbacks["apply_failure"](fix_id)
                callbacks["build"](fix_id, True)
                callbacks["tests"](fix_id, True)
                submit_tool.invoke(
                    {
                        "edits": edits,
                        "summary": "stale verified claim",
                        "status": "verified",
                    }
                )

            mock_agent.invoke.side_effect = invoke_side_effect
            return mock_agent

        with (
            patch("src.agent.fix_agent.ChatOpenAI"),
            patch(
                "src.agent.fix_agent.make_apply_fix_tool",
                side_effect=fake_apply_tool,
            ),
            patch(
                "src.agent.fix_agent.make_run_build_tool",
                side_effect=fake_build_tool,
            ),
            patch(
                "src.agent.fix_agent.make_run_tests_tool",
                side_effect=fake_tests_tool,
            ),
            patch(
                "src.agent.fix_agent.create_react_agent",
                side_effect=fake_create_react_agent,
            ),
        ):
            proposal = agent.run(_make_report())

        assert proposal.status == "draft"
        assert "Downgraded to draft" in proposal.summary
