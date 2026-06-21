"""Integration tests for commit_fix.py main flow."""

import json
import os
import sys
from unittest.mock import MagicMock, call, patch

import pytest

import commit_fix as cf
from src.models import FixEdit, FixProposal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_UUID = "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d"
_DIAG_UUID = "b2c3d4e5-f6a7-4b8c-9d0e-1f2a3b4c5d6e"


def _make_proposal(
    proposal_id: str = _VALID_UUID,
    diagnosis_id: str = _DIAG_UUID,
    status: str = "verified",
    edits: list[FixEdit] | None = None,
    summary: str = "Fixed null check",
) -> FixProposal:
    if edits is None:
        edits = [FixEdit(file="A.java", start_line=1, end_line=1, new_content="fix\n", reason="r")]
    return FixProposal(
        proposal_id=proposal_id,
        diagnosis_id=diagnosis_id,
        created_at="2026-01-01T00:00:00+00:00",
        status=status,
        edits=edits,
        summary=summary,
    )


def _write_proposal(ws_root: str, proposal: FixProposal) -> None:
    fix_dir = os.path.join(ws_root, "fix")
    os.makedirs(fix_dir, exist_ok=True)
    path = os.path.join(fix_dir, f"{proposal.proposal_id}.json")
    data = {
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
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def _write_diagnosis(ws_root: str, diagnosis_id: str) -> None:
    diag_dir = os.path.join(ws_root, "diagnosis")
    os.makedirs(diag_dir, exist_ok=True)
    path = os.path.join(diag_dir, f"{diagnosis_id}.json")
    data = {
        "diagnosis_id": diagnosis_id,
        "created_at": "2026-01-01T00:00:00+00:00",
        "status": "completed",
        "input": {"stack_trace": "NPE", "source_dir": "/src"},
        "conclusion": None,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCommitFix:
    @pytest.fixture(autouse=True)
    def _noop_file_lock(self):
        with patch("commit_fix.FileLock"):
            yield

    def _run(self, argv: list[str]) -> None:
        with patch.object(sys, "argv", ["commit_fix"] + argv):
            cf.main()

    def test_happy_path_no_conflict(self, tmp_path):
        ws = str(tmp_path / "ws")
        proposal = _make_proposal()
        _write_proposal(ws, proposal)
        _write_diagnosis(ws, _DIAG_UUID)

        with (
            patch("commit_fix.svn_dirty_files", return_value=[]),
            patch("commit_fix.snapshot_hashes", return_value={"A.java": "abc"}),
            patch("commit_fix.svn_update"),
            patch("commit_fix.detect_conflicts", return_value=[]),
            patch("commit_fix.generate_diff", return_value="diff output\n"),
            patch("commit_fix.apply_edits"),
            patch("commit_fix.svn_commit", return_value="99") as mock_commit,
        ):
            config = MagicMock(
                target_project_dir=str(tmp_path / "project"),
                max_retry=3,
                build_command="",
                test_command="",
            )
            cf._run_with_workspace(ws, _VALID_UUID, config, max_retry=3, dry_run=False, yes=True)
            mock_commit.assert_called_once_with(
                str(tmp_path / "project"), "[bughunter] Fixed null check", ["A.java"]
            )

    def test_dirty_edited_files_abort_before_snapshot(self, tmp_path):
        ws = str(tmp_path / "ws")
        proposal = _make_proposal()
        _write_proposal(ws, proposal)
        _write_diagnosis(ws, _DIAG_UUID)

        with (
            patch("commit_fix.svn_dirty_files", return_value=["A.java"]),
            patch("commit_fix.snapshot_hashes") as mock_snapshot,
            patch("commit_fix.svn_update"),
        ):
            config = MagicMock(
                target_project_dir=str(tmp_path / "project"),
                max_retry=3,
                build_command="",
                test_command="",
            )
            with pytest.raises(SystemExit) as exc_info:
                cf._run_with_workspace(ws, _VALID_UUID, config, max_retry=3, dry_run=False, yes=True)
            assert exc_info.value.code == 1
            mock_snapshot.assert_not_called()

    def test_draft_proposal_rejected(self, tmp_path):
        ws = str(tmp_path / "ws")
        proposal = _make_proposal(status="draft")
        _write_proposal(ws, proposal)
        _write_diagnosis(ws, _DIAG_UUID)

        config = MagicMock(
            target_project_dir=str(tmp_path / "project"),
            max_retry=3,
            build_command="",
            test_command="",
        )
        with pytest.raises(SystemExit) as exc_info:
            cf._run_with_workspace(ws, proposal.proposal_id, config, max_retry=3, dry_run=False, yes=True)
        assert exc_info.value.code == 1

    def test_dry_run_does_not_call_apply_or_commit(self, tmp_path):
        ws = str(tmp_path / "ws")
        proposal = _make_proposal()
        _write_proposal(ws, proposal)
        _write_diagnosis(ws, _DIAG_UUID)

        with (
            patch("commit_fix.svn_dirty_files", return_value=[]),
            patch("commit_fix.snapshot_hashes", return_value={}),
            patch("commit_fix.svn_update"),
            patch("commit_fix.detect_conflicts", return_value=[]),
            patch("commit_fix.generate_diff", return_value="diff\n"),
            patch("commit_fix.apply_edits") as mock_apply,
            patch("commit_fix.svn_commit") as mock_commit,
        ):
            with pytest.raises(SystemExit) as exc_info:
                config = MagicMock(
                    target_project_dir=str(tmp_path / "project"),
                    max_retry=3,
                    build_command="",
                    test_command="",
                )
                cf._run_with_workspace(ws, proposal.proposal_id, config, max_retry=3, dry_run=True, yes=False)
            assert exc_info.value.code == 0
            mock_apply.assert_not_called()
            mock_commit.assert_not_called()

    def test_no_yes_shows_diff_and_exits_zero(self, tmp_path):
        ws = str(tmp_path / "ws")
        proposal = _make_proposal()
        _write_proposal(ws, proposal)
        _write_diagnosis(ws, _DIAG_UUID)

        with (
            patch("commit_fix.svn_dirty_files", return_value=[]),
            patch("commit_fix.snapshot_hashes", return_value={}),
            patch("commit_fix.svn_update"),
            patch("commit_fix.detect_conflicts", return_value=[]),
            patch("commit_fix.generate_diff", return_value="diff\n"),
            patch("commit_fix.apply_edits") as mock_apply,
            patch("commit_fix.svn_commit") as mock_commit,
        ):
            with pytest.raises(SystemExit) as exc_info:
                config = MagicMock(
                    target_project_dir=str(tmp_path / "project"),
                    max_retry=3,
                    build_command="",
                    test_command="",
                )
                cf._run_with_workspace(ws, proposal.proposal_id, config, max_retry=3, dry_run=False, yes=False)
            assert exc_info.value.code == 0
            mock_apply.assert_not_called()
            mock_commit.assert_not_called()

    def test_conflict_triggers_svn_revert_after_max_retry(self, tmp_path):
        ws = str(tmp_path / "ws")
        proposal = _make_proposal()
        _write_proposal(ws, proposal)
        _write_diagnosis(ws, _DIAG_UUID)

        with (
            patch("commit_fix.svn_dirty_files", return_value=[]),
            patch("commit_fix.snapshot_hashes", return_value={"A.java": "abc"}),
            patch("commit_fix.svn_update"),
            patch("commit_fix.detect_conflicts", return_value=["A.java"]),
            patch("commit_fix.svn_revert") as mock_revert,
            patch("commit_fix.FixAgent") as mock_agent_cls,
        ):
            mock_agent = MagicMock()
            mock_agent.run.return_value = _make_proposal()
            mock_agent_cls.return_value = mock_agent

            config = MagicMock(
                target_project_dir=str(tmp_path / "project"),
                max_retry=0,
                build_command="",
                test_command="",
            )
            with pytest.raises(SystemExit) as exc_info:
                cf._run_with_workspace(ws, proposal.proposal_id, config, max_retry=0, dry_run=False, yes=True)
            assert exc_info.value.code == 1
            mock_revert.assert_called_once()

    def test_apply_edits_failure_calls_svn_revert(self, tmp_path):
        ws = str(tmp_path / "ws")
        proposal = _make_proposal()
        _write_proposal(ws, proposal)
        _write_diagnosis(ws, _DIAG_UUID)

        with (
            patch("commit_fix.svn_dirty_files", return_value=[]),
            patch("commit_fix.snapshot_hashes", return_value={}),
            patch("commit_fix.svn_update"),
            patch("commit_fix.detect_conflicts", return_value=[]),
            patch("commit_fix.generate_diff", return_value="diff\n"),
            patch("commit_fix.apply_edits", side_effect=OSError("disk full")),
            patch("commit_fix.svn_revert") as mock_revert,
        ):
            config = MagicMock(
                target_project_dir=str(tmp_path / "project"),
                max_retry=3,
                build_command="",
                test_command="",
            )
            with pytest.raises(SystemExit) as exc_info:
                cf._run_with_workspace(ws, proposal.proposal_id, config, max_retry=3, dry_run=False, yes=True)
            assert exc_info.value.code == 1
            mock_revert.assert_called_once()

    def test_svn_commit_failure_calls_svn_revert(self, tmp_path):
        ws = str(tmp_path / "ws")
        proposal = _make_proposal()
        _write_proposal(ws, proposal)
        _write_diagnosis(ws, _DIAG_UUID)

        with (
            patch("commit_fix.svn_dirty_files", return_value=[]),
            patch("commit_fix.snapshot_hashes", return_value={}),
            patch("commit_fix.svn_update"),
            patch("commit_fix.detect_conflicts", return_value=[]),
            patch("commit_fix.generate_diff", return_value="diff\n"),
            patch("commit_fix.apply_edits"),
            patch("commit_fix.svn_commit", side_effect=RuntimeError("locked")),
            patch("commit_fix.svn_revert") as mock_revert,
        ):
            config = MagicMock(
                target_project_dir=str(tmp_path / "project"),
                max_retry=3,
                build_command="",
                test_command="",
            )
            with pytest.raises(SystemExit) as exc_info:
                cf._run_with_workspace(ws, proposal.proposal_id, config, max_retry=3, dry_run=False, yes=True)
            assert exc_info.value.code == 1
            mock_revert.assert_called_once()

    def test_build_failure_reverts_and_aborts(self, tmp_path):
        ws = str(tmp_path / "ws")
        proposal = _make_proposal()
        _write_proposal(ws, proposal)
        _write_diagnosis(ws, _DIAG_UUID)

        failed_proc = MagicMock(returncode=1, stdout="BUILD FAILURE\n", stderr="")
        with (
            patch("commit_fix.svn_dirty_files", return_value=[]),
            patch("commit_fix.snapshot_hashes", return_value={}),
            patch("commit_fix.svn_update"),
            patch("commit_fix.detect_conflicts", return_value=[]),
            patch("commit_fix.generate_diff", return_value="diff\n"),
            patch("commit_fix.apply_edits"),
            patch("commit_fix.subprocess.run", return_value=failed_proc),
            patch("commit_fix.svn_revert") as mock_revert,
            patch("commit_fix.svn_commit") as mock_commit,
        ):
            config = MagicMock(
                target_project_dir=str(tmp_path / "project"),
                max_retry=3,
                build_command="mvn package",
                test_command="",
            )
            with pytest.raises(SystemExit) as exc_info:
                cf._run_with_workspace(ws, proposal.proposal_id, config, max_retry=3, dry_run=False, yes=True)
            assert exc_info.value.code == 1
            mock_revert.assert_called_once()
            mock_commit.assert_not_called()

    def test_test_failure_reverts_and_aborts(self, tmp_path):
        ws = str(tmp_path / "ws")
        proposal = _make_proposal()
        _write_proposal(ws, proposal)
        _write_diagnosis(ws, _DIAG_UUID)

        failed_proc = MagicMock(returncode=1, stdout="Tests run: 1, Failures: 1\n", stderr="")
        with (
            patch("commit_fix.svn_dirty_files", return_value=[]),
            patch("commit_fix.snapshot_hashes", return_value={}),
            patch("commit_fix.svn_update"),
            patch("commit_fix.detect_conflicts", return_value=[]),
            patch("commit_fix.generate_diff", return_value="diff\n"),
            patch("commit_fix.apply_edits"),
            patch("commit_fix.subprocess.run", return_value=failed_proc),
            patch("commit_fix.svn_revert") as mock_revert,
            patch("commit_fix.svn_commit") as mock_commit,
        ):
            config = MagicMock(
                target_project_dir=str(tmp_path / "project"),
                max_retry=3,
                build_command="",
                test_command="mvn test",
            )
            with pytest.raises(SystemExit) as exc_info:
                cf._run_with_workspace(ws, proposal.proposal_id, config, max_retry=3, dry_run=False, yes=True)
            assert exc_info.value.code == 1
            mock_revert.assert_called_once()
            mock_commit.assert_not_called()

    def test_fix_agent_returns_draft_on_retry_exits(self, tmp_path):
        ws = str(tmp_path / "ws")
        proposal = _make_proposal()
        _write_proposal(ws, proposal)
        _write_diagnosis(ws, _DIAG_UUID)

        with (
            patch("commit_fix.svn_dirty_files", return_value=[]),
            patch("commit_fix.snapshot_hashes", return_value={"A.java": "abc"}),
            patch("commit_fix.svn_update"),
            patch("commit_fix.detect_conflicts", return_value=["A.java"]),
            patch("commit_fix.FixAgent") as mock_agent_cls,
        ):
            mock_agent = MagicMock()
            mock_agent.run.return_value = _make_proposal(status="draft")
            mock_agent_cls.return_value = mock_agent

            config = MagicMock(
                target_project_dir=str(tmp_path / "project"),
                max_retry=3,
                build_command="",
                test_command="",
            )
            with pytest.raises(SystemExit) as exc_info:
                cf._run_with_workspace(ws, proposal.proposal_id, config, max_retry=3, dry_run=False, yes=True)
            assert exc_info.value.code == 1
            mock_agent.run.assert_called_once()

    def test_conflict_then_retry_success(self, tmp_path):
        ws = str(tmp_path / "ws")
        proposal = _make_proposal()
        retry_proposal = _make_proposal()
        _write_proposal(ws, proposal)
        _write_diagnosis(ws, _DIAG_UUID)

        detect_call_count = [0]

        def _mock_detect(old_hashes, source_dir):
            detect_call_count[0] += 1
            return ["A.java"] if detect_call_count[0] == 1 else []

        with (
            patch("commit_fix.svn_dirty_files", return_value=[]),
            patch("commit_fix.snapshot_hashes", return_value={"A.java": "abc"}),
            patch("commit_fix.svn_update"),
            patch("commit_fix.detect_conflicts", side_effect=_mock_detect),
            patch("commit_fix.generate_diff", return_value="diff\n"),
            patch("commit_fix.apply_edits"),
            patch("commit_fix.svn_commit", return_value="100") as mock_commit,
            patch("commit_fix.FixAgent") as mock_agent_cls,
        ):
            mock_agent = MagicMock()
            mock_agent.run.return_value = retry_proposal
            mock_agent_cls.return_value = mock_agent

            config = MagicMock(
                target_project_dir=str(tmp_path / "project"),
                max_retry=3,
                build_command="",
                test_command="",
            )
            cf._run_with_workspace(ws, _VALID_UUID, config, max_retry=3, dry_run=False, yes=True)

            mock_agent.run.assert_called_once()
            mock_commit.assert_called_once_with(
                str(tmp_path / "project"),
                "[bughunter] Fixed null check",
                ["A.java"],
            )

    def _write_proposal_raw(self, ws: str, proposal_id: str, file_path: str) -> None:
        """Write a proposal JSON with a custom (possibly malicious) file path."""
        fix_dir = os.path.join(ws, "fix")
        os.makedirs(fix_dir, exist_ok=True)
        data = {
            "proposal_id": proposal_id,
            "diagnosis_id": _DIAG_UUID,
            "created_at": "2026-01-01T00:00:00+00:00",
            "status": "verified",
            "summary": "bad proposal",
            "edits": [
                {
                    "file": file_path,
                    "start_line": 1,
                    "end_line": 1,
                    "new_content": "x\n",
                    "reason": "test",
                }
            ],
        }
        with open(os.path.join(fix_dir, f"{proposal_id}.json"), "w", encoding="utf-8") as fh:
            json.dump(data, fh)

    def test_load_proposal_rejects_traversal_path(self, tmp_path):
        ws = str(tmp_path / "ws")
        self._write_proposal_raw(ws, _VALID_UUID, "../evil.java")
        _write_diagnosis(ws, _DIAG_UUID)

        config = MagicMock(
            target_project_dir=str(tmp_path / "project"),
            max_retry=3,
            build_command="",
            test_command="",
        )
        with pytest.raises(SystemExit) as exc_info:
            cf._run_with_workspace(ws, _VALID_UUID, config, max_retry=3, dry_run=False, yes=True)
        assert exc_info.value.code == 1

    def test_load_proposal_rejects_absolute_path(self, tmp_path):
        ws = str(tmp_path / "ws")
        self._write_proposal_raw(ws, _VALID_UUID, "/etc/passwd")
        _write_diagnosis(ws, _DIAG_UUID)

        config = MagicMock(
            target_project_dir=str(tmp_path / "project"),
            max_retry=3,
            build_command="",
            test_command="",
        )
        with pytest.raises(SystemExit) as exc_info:
            cf._run_with_workspace(ws, _VALID_UUID, config, max_retry=3, dry_run=False, yes=True)
        assert exc_info.value.code == 1

    def test_max_retry_zero_exits_on_first_conflict(self, tmp_path):
        ws = str(tmp_path / "ws")
        proposal = _make_proposal()
        _write_proposal(ws, proposal)
        _write_diagnosis(ws, _DIAG_UUID)

        with (
            patch("commit_fix.svn_dirty_files", return_value=[]),
            patch("commit_fix.snapshot_hashes", return_value={"A.java": "abc"}),
            patch("commit_fix.svn_update"),
            patch("commit_fix.detect_conflicts", return_value=["A.java"]),
            patch("commit_fix.svn_revert"),
            patch("commit_fix.FixAgent") as mock_agent_cls,
        ):
            config = MagicMock(
                target_project_dir=str(tmp_path / "project"),
                max_retry=0,
                build_command="",
                test_command="",
            )
            with pytest.raises(SystemExit) as exc_info:
                cf._run_with_workspace(ws, proposal.proposal_id, config, max_retry=0, dry_run=False, yes=True)
            assert exc_info.value.code == 1
            mock_agent_cls.assert_not_called()

    def test_load_proposal_rejects_non_uuid(self, tmp_path):
        ws = str(tmp_path / "ws")
        config = MagicMock(target_project_dir=str(tmp_path / "project"), max_retry=3)
        with pytest.raises(SystemExit) as exc_info:
            cf._run_with_workspace(ws, "../evil", config, max_retry=3, dry_run=False, yes=True)
        assert exc_info.value.code == 1

    def test_load_proposal_file_not_found_exits(self, tmp_path):
        ws = str(tmp_path / "ws")
        os.makedirs(os.path.join(ws, "fix"), exist_ok=True)
        _write_diagnosis(ws, _DIAG_UUID)
        config = MagicMock(target_project_dir=str(tmp_path / "project"), max_retry=3)
        with pytest.raises(SystemExit) as exc_info:
            cf._run_with_workspace(ws, _VALID_UUID, config, max_retry=3, dry_run=False, yes=True)
        assert exc_info.value.code == 1

    def test_load_proposal_corrupt_json_exits(self, tmp_path):
        ws = str(tmp_path / "ws")
        fix_dir = os.path.join(ws, "fix")
        os.makedirs(fix_dir, exist_ok=True)
        with open(os.path.join(fix_dir, f"{_VALID_UUID}.json"), "w", encoding="utf-8") as fh:
            fh.write("{not valid json")
        _write_diagnosis(ws, _DIAG_UUID)
        config = MagicMock(target_project_dir=str(tmp_path / "project"), max_retry=3)
        with pytest.raises(SystemExit) as exc_info:
            cf._run_with_workspace(ws, _VALID_UUID, config, max_retry=3, dry_run=False, yes=True)
        assert exc_info.value.code == 1

    def test_snapshot_hashes_failure_exits(self, tmp_path):
        ws = str(tmp_path / "ws")
        proposal = _make_proposal()
        _write_proposal(ws, proposal)
        _write_diagnosis(ws, _DIAG_UUID)

        with (
            patch("commit_fix.svn_dirty_files", return_value=[]),
            patch("commit_fix.snapshot_hashes", side_effect=OSError("permission denied")),
        ):
            config = MagicMock(
                target_project_dir=str(tmp_path / "project"),
                max_retry=3,
                build_command="",
                test_command="",
            )
            with pytest.raises(SystemExit) as exc_info:
                cf._run_with_workspace(ws, _VALID_UUID, config, max_retry=3, dry_run=False, yes=True)
            assert exc_info.value.code == 1

    def test_svn_update_failure_exits(self, tmp_path):
        ws = str(tmp_path / "ws")
        proposal = _make_proposal()
        _write_proposal(ws, proposal)
        _write_diagnosis(ws, _DIAG_UUID)

        with (
            patch("commit_fix.svn_dirty_files", return_value=[]),
            patch("commit_fix.snapshot_hashes", return_value={}),
            patch("commit_fix.svn_update", side_effect=RuntimeError("network error")),
        ):
            config = MagicMock(
                target_project_dir=str(tmp_path / "project"),
                max_retry=3,
                build_command="",
                test_command="",
            )
            with pytest.raises(SystemExit) as exc_info:
                cf._run_with_workspace(ws, _VALID_UUID, config, max_retry=3, dry_run=False, yes=True)
            assert exc_info.value.code == 1

    def test_revert_and_abort_warns_when_revert_fails(self, tmp_path, capsys):
        with patch("commit_fix.svn_revert", side_effect=RuntimeError("revert error")):
            with pytest.raises(SystemExit) as exc_info:
                cf._revert_and_abort(str(tmp_path), ["A.java"], "something failed")
        assert exc_info.value.code == 1
        assert "revert also failed" in capsys.readouterr().err


class TestCommitFixLocking:
    def test_lock_contention_exits_with_error(self, tmp_path):
        ws = str(tmp_path / "ws")
        proposal = _make_proposal()
        _write_proposal(ws, proposal)
        _write_diagnosis(ws, _DIAG_UUID)

        from filelock import Timeout as FileLockTimeout

        mock_lock = MagicMock()
        mock_lock.__enter__ = MagicMock(side_effect=FileLockTimeout(".bughunter.lock"))

        config = MagicMock(
            target_project_dir=str(tmp_path / "project"),
            max_retry=3,
            build_command="",
            test_command="",
        )
        with patch("commit_fix.FileLock", return_value=mock_lock):
            with pytest.raises(SystemExit) as exc_info:
                cf._run_with_workspace(ws, _VALID_UUID, config, max_retry=3, dry_run=False, yes=True)
        assert exc_info.value.code == 1
