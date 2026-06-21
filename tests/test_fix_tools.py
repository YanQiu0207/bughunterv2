"""Unit tests for apply_fix, run_build, and run_tests tools."""

import os
import subprocess
import sys
from unittest.mock import patch

import pytest

import src.tools.apply_fix as apply_fix_module
from src.tools.apply_fix import make_apply_fix_tool
from src.tools.run_build import make_run_build_tool
from src.tools.run_tests import make_run_tests_tool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _setup_workspace(tmp_path, fix_id: str) -> tuple[str, str]:
    ws_root = str(tmp_path / "workspace")
    ws_path = os.path.join(ws_root, "fix", fix_id)
    os.makedirs(ws_path, exist_ok=True)
    return ws_root, ws_path


# ---------------------------------------------------------------------------
# apply_fix
# ---------------------------------------------------------------------------

_VALID_UUID = "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d"


class TestApplyFix:
    FIX_ID = _VALID_UUID

    @pytest.fixture(autouse=True)
    def svn_status(self):
        with patch("src.tools.apply_fix.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=["svn", "status"],
                returncode=0,
                stdout="",
                stderr="",
            )
            yield mock_run

    def _tool(self, workspace_root: str, target_dir: str):
        return make_apply_fix_tool(workspace_root, target_dir)

    def test_creates_workspace_and_applies_edit(self, tmp_path):
        target = tmp_path / "project"
        ws_root = tmp_path / "workspace"
        java_rel = "src/Foo.java"
        java_abs = target / java_rel

        _write(str(java_abs), "line1\nline2\nline3\n")

        tool = self._tool(str(ws_root), str(target))
        result = tool.invoke(
            {
                "fix_id": self.FIX_ID,
                "edits": [
                    {
                        "file": java_rel,
                        "start_line": 2,
                        "end_line": 2,
                        "new_content": "REPLACED\n",
                        "reason": "test",
                    }
                ],
            }
        )

        assert "[apply_fix] Applied 1 edit" in result
        ws_file = ws_root / "fix" / self.FIX_ID / java_rel
        assert _read(str(ws_file)) == "line1\nREPLACED\nline3\n"

    def test_cache_file_unchanged_after_edit(self, tmp_path):
        target = tmp_path / "project"
        ws_root = tmp_path / "workspace"
        java_rel = "src/Bar.java"
        java_abs = target / java_rel

        _write(str(java_abs), "a\nb\nc\n")

        tool = self._tool(str(ws_root), str(target))
        tool.invoke(
            {
                "fix_id": self.FIX_ID,
                "edits": [
                    {
                        "file": java_rel,
                        "start_line": 1,
                        "end_line": 1,
                        "new_content": "X\n",
                        "reason": "test",
                    }
                ],
            }
        )

        assert _read(str(java_abs)) == "a\nb\nc\n"

    def test_workspace_file_edit_does_not_mutate_cache(self, tmp_path):
        target = tmp_path / "project"
        ws_root = tmp_path / "workspace"
        java_rel = "src/Baz.java"
        java_abs = target / java_rel

        _write(str(java_abs), "a\nb\n")

        tool = self._tool(str(ws_root), str(target))
        tool.invoke(
            {
                "fix_id": self.FIX_ID,
                "edits": [
                    {
                        "file": java_rel,
                        "start_line": 1,
                        "end_line": 1,
                        "new_content": "NEW\n",
                        "reason": "test",
                    }
                ],
            }
        )

        ws_file = ws_root / "fix" / self.FIX_ID / java_rel
        assert _read(str(ws_file)) == "NEW\nb\n"
        assert _read(str(java_abs)) == "a\nb\n"

    def test_dirty_svn_cache_returns_error_without_workspace(
        self, tmp_path, svn_status
    ):
        target = tmp_path / "project"
        ws_root = tmp_path / "workspace"
        _write(str(target / "A.java"), "x\n")
        svn_status.return_value = subprocess.CompletedProcess(
            args=["svn", "status"],
            returncode=0,
            stdout="M       A.java\n",
            stderr="",
        )

        tool = self._tool(str(ws_root), str(target))
        result = tool.invoke(
            {
                "fix_id": self.FIX_ID,
                "edits": [
                    {
                        "file": "A.java",
                        "start_line": 1,
                        "end_line": 1,
                        "new_content": "y\n",
                        "reason": "r",
                    }
                ],
            }
        )

        assert "[apply_fix] Error" in result
        assert "local changes" in result
        assert not (ws_root / "fix" / self.FIX_ID).exists()

    def test_svn_status_failure_returns_error_without_workspace(
        self, tmp_path, svn_status
    ):
        target = tmp_path / "project"
        ws_root = tmp_path / "workspace"
        _write(str(target / "A.java"), "x\n")
        svn_status.return_value = subprocess.CompletedProcess(
            args=["svn", "status"],
            returncode=1,
            stdout="",
            stderr="not a working copy",
        )

        tool = self._tool(str(ws_root), str(target))
        result = tool.invoke(
            {
                "fix_id": self.FIX_ID,
                "edits": [
                    {
                        "file": "A.java",
                        "start_line": 1,
                        "end_line": 1,
                        "new_content": "y\n",
                        "reason": "r",
                    }
                ],
            }
        )

        assert "[apply_fix] Error" in result
        assert "svn status failed" in result
        assert "not a working copy" in result
        assert not (ws_root / "fix" / self.FIX_ID).exists()

    def test_svn_status_timeout_returns_error_without_workspace(
        self, tmp_path, svn_status
    ):
        target = tmp_path / "project"
        ws_root = tmp_path / "workspace"
        _write(str(target / "A.java"), "x\n")
        svn_status.side_effect = subprocess.TimeoutExpired(
            cmd="svn status",
            timeout=30,
            output="x" * 3000,
            stderr="error detail",
        )

        tool = self._tool(str(ws_root), str(target))
        result = tool.invoke(
            {
                "fix_id": self.FIX_ID,
                "edits": [
                    {
                        "file": "A.java",
                        "start_line": 1,
                        "end_line": 1,
                        "new_content": "y\n",
                        "reason": "r",
                    }
                ],
            }
        )

        assert "[apply_fix] Error" in result
        assert "timed out after 30 seconds" in result
        assert "truncated" in result
        assert not (ws_root / "fix" / self.FIX_ID).exists()

    def test_svn_status_stderr_output_rejected(self, tmp_path, svn_status):
        target = tmp_path / "project"
        ws_root = tmp_path / "workspace"
        _write(str(target / "A.java"), "x\n")
        svn_status.return_value = subprocess.CompletedProcess(
            args=["svn", "status"],
            returncode=0,
            stdout="",
            stderr="warning: suspicious working copy\n",
        )

        tool = self._tool(str(ws_root), str(target))
        result = tool.invoke(
            {
                "fix_id": self.FIX_ID,
                "edits": [
                    {
                        "file": "A.java",
                        "start_line": 1,
                        "end_line": 1,
                        "new_content": "y\n",
                        "reason": "r",
                    }
                ],
            }
        )

        assert "[apply_fix] Error" in result
        assert "local changes" in result
        assert not (ws_root / "fix" / self.FIX_ID).exists()

    def test_dirty_svn_cache_rejected_when_workspace_exists(
        self, tmp_path, svn_status
    ):
        target = tmp_path / "project"
        ws_root = tmp_path / "workspace"
        _write(str(target / "A.java"), "original\n")
        _write(str(target / "B.java"), "other\n")
        tool = self._tool(str(ws_root), str(target))

        result = tool.invoke(
            {
                "fix_id": self.FIX_ID,
                "edits": [
                    {
                        "file": "A.java",
                        "start_line": 1,
                        "end_line": 1,
                        "new_content": "round1\n",
                        "reason": "r1",
                    }
                ],
            }
        )
        assert "[apply_fix] Applied" in result

        svn_status.return_value = subprocess.CompletedProcess(
            args=["svn", "status"],
            returncode=0,
            stdout="M       A.java\n",
            stderr="",
        )
        result2 = tool.invoke(
            {
                "fix_id": self.FIX_ID,
                "edits": [
                    {
                        "file": "B.java",
                        "start_line": 1,
                        "end_line": 1,
                        "new_content": "round2\n",
                        "reason": "r2",
                    }
                ],
            }
        )

        assert "[apply_fix] Error" in result2
        assert "local changes" in result2
        ws_path = ws_root / "fix" / self.FIX_ID
        assert _read(str(ws_path / "A.java")) == "round1\n"
        assert _read(str(ws_path / "B.java")) == "other\n"

    def test_unexpected_fix_id_rejected(self, tmp_path):
        target = tmp_path / "project"
        ws_root = tmp_path / "workspace"
        _write(str(target / "A.java"), "x\n")
        expected = "11111111-1111-4111-8111-111111111111"
        tool = make_apply_fix_tool(
            str(ws_root), str(target), expected_fix_id=expected
        )

        result = tool.invoke(
            {
                "fix_id": self.FIX_ID,
                "edits": [
                    {
                        "file": "A.java",
                        "start_line": 1,
                        "end_line": 1,
                        "new_content": "y\n",
                        "reason": "r",
                    }
                ],
            }
        )

        assert "[apply_fix] Error" in result
        assert "does not match" in result

    def test_restore_unlinks_workspace_symlink_before_copy(self, tmp_path):
        target = tmp_path / "project"
        ws_root = tmp_path / "workspace"
        outside = tmp_path / "outside.txt"
        _write(str(target / "A.java"), "original\n")
        _write(str(target / "B.java"), "other\n")
        outside.write_text("outside\n", encoding="utf-8")
        tool = self._tool(str(ws_root), str(target))

        result = tool.invoke(
            {
                "fix_id": self.FIX_ID,
                "edits": [
                    {
                        "file": "A.java",
                        "start_line": 1,
                        "end_line": 1,
                        "new_content": "round1\n",
                        "reason": "r1",
                    }
                ],
            }
        )
        assert "[apply_fix] Applied" in result

        ws_a = ws_root / "fix" / self.FIX_ID / "A.java"
        try:
            os.unlink(str(ws_a))
            os.symlink(str(outside), str(ws_a))
        except (OSError, NotImplementedError) as exc:
            pytest.skip(f"symlink not available: {exc}")

        result2 = tool.invoke(
            {
                "fix_id": self.FIX_ID,
                "edits": [
                    {
                        "file": "B.java",
                        "start_line": 1,
                        "end_line": 1,
                        "new_content": "round2\n",
                        "reason": "r2",
                    }
                ],
            }
        )

        assert "[apply_fix] Applied" in result2
        assert outside.read_text(encoding="utf-8") == "outside\n"
        assert not os.path.islink(str(ws_a))
        assert _read(str(ws_a)) == "original\n"

    def test_reapply_same_file_restores_to_original(self, tmp_path):
        target = tmp_path / "project"
        ws_root = tmp_path / "workspace"
        java_rel = "src/Re.java"
        java_abs = target / java_rel

        _write(str(java_abs), "original\n")
        tool = self._tool(str(ws_root), str(target))

        tool.invoke(
            {
                "fix_id": self.FIX_ID,
                "edits": [
                    {
                        "file": java_rel,
                        "start_line": 1,
                        "end_line": 1,
                        "new_content": "first edit\n",
                        "reason": "round 1",
                    }
                ],
            }
        )
        tool.invoke(
            {
                "fix_id": self.FIX_ID,
                "edits": [
                    {
                        "file": java_rel,
                        "start_line": 1,
                        "end_line": 1,
                        "new_content": "second edit\n",
                        "reason": "round 2",
                    }
                ],
            }
        )

        ws_content = _read(str(ws_root / "fix" / self.FIX_ID / java_rel))
        # Round 2 must start from original, not from "first edit".
        assert ws_content == "second edit\n"

    def test_cross_file_cross_round_restores_first_file(self, tmp_path):
        target = tmp_path / "project"
        ws_root = tmp_path / "workspace"

        _write(str(target / "A.java"), "a-original\n")
        _write(str(target / "B.java"), "b-original\n")
        tool = self._tool(str(ws_root), str(target))

        # Round 1: edit only A.java
        tool.invoke(
            {
                "fix_id": self.FIX_ID,
                "edits": [
                    {
                        "file": "A.java",
                        "start_line": 1,
                        "end_line": 1,
                        "new_content": "a-round1\n",
                        "reason": "r1",
                    }
                ],
            }
        )

        # Round 2: edit only B.java — A.java must be restored to original
        tool.invoke(
            {
                "fix_id": self.FIX_ID,
                "edits": [
                    {
                        "file": "B.java",
                        "start_line": 1,
                        "end_line": 1,
                        "new_content": "b-round2\n",
                        "reason": "r2",
                    }
                ],
            }
        )

        ws_path = ws_root / "fix" / self.FIX_ID
        assert _read(str(ws_path / "A.java")) == "a-original\n"
        assert _read(str(ws_path / "B.java")) == "b-round2\n"

    def test_pre_check_atomicity_on_missing_file(self, tmp_path):
        target = tmp_path / "project"
        ws_root = tmp_path / "workspace"

        _write(str(target / "Exists.java"), "original\n")
        tool = self._tool(str(ws_root), str(target))

        # Batch where first file exists, second does not.
        result = tool.invoke(
            {
                "fix_id": self.FIX_ID,
                "edits": [
                    {
                        "file": "Exists.java",
                        "start_line": 1,
                        "end_line": 1,
                        "new_content": "modified\n",
                        "reason": "r",
                    },
                    {
                        "file": "Ghost.java",
                        "start_line": 1,
                        "end_line": 1,
                        "new_content": "x\n",
                        "reason": "r",
                    },
                ],
            }
        )

        assert "[apply_fix] Error" in result
        ws_file = ws_root / "fix" / self.FIX_ID / "Exists.java"
        # Exists.java must be unchanged because the pre-check aborted before any write.
        if ws_file.exists():
            assert _read(str(ws_file)) == "original\n"

    def test_too_many_edits_returns_error(self, tmp_path):
        target = tmp_path / "project"
        ws_root = tmp_path / "workspace"
        edits = [
            {
                "file": "src/X.java",
                "start_line": 1,
                "end_line": 1,
                "new_content": "x\n",
                "reason": "r",
            }
            for _ in range(51)
        ]
        tool = self._tool(str(ws_root), str(target))
        result = tool.invoke({"fix_id": self.FIX_ID, "edits": edits})
        assert "[apply_fix] Error" in result
        assert "50" in result

    def test_missing_file_returns_error(self, tmp_path):
        target = tmp_path / "project"
        ws_root = tmp_path / "workspace"
        _write(str(target / "src" / "Exists.java"), "x\n")
        tool = self._tool(str(ws_root), str(target))
        # Create workspace via a valid first edit.
        tool.invoke(
            {
                "fix_id": self.FIX_ID,
                "edits": [
                    {
                        "file": "src/Exists.java",
                        "start_line": 1,
                        "end_line": 1,
                        "new_content": "y\n",
                        "reason": "seed",
                    }
                ],
            }
        )
        result = tool.invoke(
            {
                "fix_id": self.FIX_ID,
                "edits": [
                    {
                        "file": "src/NoSuch.java",
                        "start_line": 1,
                        "end_line": 1,
                        "new_content": "z\n",
                        "reason": "bad",
                    }
                ],
            }
        )
        assert "[apply_fix] Error" in result
        assert "NoSuch.java" in result

    def test_invalid_line_range_returns_error(self, tmp_path):
        target = tmp_path / "project"
        ws_root = tmp_path / "workspace"
        _write(str(target / "src" / "Short.java"), "only one line\n")
        tool = self._tool(str(ws_root), str(target))
        result = tool.invoke(
            {
                "fix_id": self.FIX_ID,
                "edits": [
                    {
                        "file": "src/Short.java",
                        "start_line": 5,
                        "end_line": 10,
                        "new_content": "oops\n",
                        "reason": "bad range",
                    }
                ],
            }
        )
        assert "[apply_fix] Error" in result

    def test_start_line_zero_returns_error(self, tmp_path):
        target = tmp_path / "project"
        ws_root = tmp_path / "workspace"
        _write(str(target / "X.java"), "line1\nline2\n")
        tool = self._tool(str(ws_root), str(target))
        result = tool.invoke(
            {
                "fix_id": self.FIX_ID,
                "edits": [
                    {
                        "file": "X.java",
                        "start_line": 0,
                        "end_line": 1,
                        "new_content": "x\n",
                        "reason": "zero start",
                    }
                ],
            }
        )
        assert "[apply_fix] Error" in result

    def test_end_before_start_returns_error(self, tmp_path):
        target = tmp_path / "project"
        ws_root = tmp_path / "workspace"
        _write(str(target / "Y.java"), "line1\nline2\nline3\n")
        tool = self._tool(str(ws_root), str(target))
        result = tool.invoke(
            {
                "fix_id": self.FIX_ID,
                "edits": [
                    {
                        "file": "Y.java",
                        "start_line": 3,
                        "end_line": 1,
                        "new_content": "x\n",
                        "reason": "inverted range",
                    }
                ],
            }
        )
        assert "[apply_fix] Error" in result

    def test_empty_new_content_returns_error(self, tmp_path):
        target = tmp_path / "project"
        ws_root = tmp_path / "workspace"
        _write(str(target / "Z.java"), "line1\n")
        tool = self._tool(str(ws_root), str(target))
        result = tool.invoke(
            {
                "fix_id": self.FIX_ID,
                "edits": [
                    {
                        "file": "Z.java",
                        "start_line": 1,
                        "end_line": 1,
                        "new_content": "",
                        "reason": "forgot newline",
                    }
                ],
            }
        )
        assert "[apply_fix] Error" in result
        assert "empty" in result

    def test_hidden_file_edit_rejected(self, tmp_path):
        target = tmp_path / "project"
        ws_root = tmp_path / "workspace"
        _write(str(target / "A.java"), "x\n")
        tool = self._tool(str(ws_root), str(target))
        result = tool.invoke(
            {
                "fix_id": self.FIX_ID,
                "edits": [
                    {
                        "file": ".fix_modified_files",
                        "start_line": 1,
                        "end_line": 1,
                        "new_content": '["../../../etc/passwd"]\n',
                        "reason": "attack",
                    }
                ],
            }
        )
        assert "[apply_fix] Error" in result
        assert "hidden" in result

    def test_path_traversal_rejected(self, tmp_path):
        target = tmp_path / "project"
        ws_root = tmp_path / "workspace"
        _write(str(target / "safe.java"), "x\n")
        tool = self._tool(str(ws_root), str(target))
        result = tool.invoke(
            {
                "fix_id": self.FIX_ID,
                "edits": [
                    {
                        "file": "../../etc/passwd",
                        "start_line": 1,
                        "end_line": 1,
                        "new_content": "evil\n",
                        "reason": "attack",
                    }
                ],
            }
        )
        assert "[apply_fix] Error" in result
        assert _read(str(target / "safe.java")) == "x\n"

    def test_invalid_fix_id_rejected(self, tmp_path):
        target = tmp_path / "project"
        ws_root = tmp_path / "workspace"
        _write(str(target / "A.java"), "x\n")
        tool = self._tool(str(ws_root), str(target))
        result = tool.invoke(
            {
                "fix_id": "../../evil",
                "edits": [
                    {
                        "file": "A.java",
                        "start_line": 1,
                        "end_line": 1,
                        "new_content": "y\n",
                        "reason": "r",
                    }
                ],
            }
        )
        assert "[apply_fix] Error" in result
        assert "UUID" in result

    def test_total_content_limit_returns_error(self, tmp_path):
        target = tmp_path / "project"
        ws_root = tmp_path / "workspace"
        _write(str(target / "Big.java"), "x\n")
        # 9 edits × ~500 KB each = ~4.5 MB > 4 MB limit
        large_content = "x" * (500 * 1024) + "\n"
        edits = [
            {
                "file": "Big.java",
                "start_line": 1,
                "end_line": 1,
                "new_content": large_content,
                "reason": f"edit {i}",
            }
            for i in range(9)
        ]
        # Use only one file to keep the edit list short (< 50 cap)
        # but make 9 separate edits with a single file
        # Actually we need non-overlapping ranges; use 1-edit per call pattern
        # For the total limit test: just one large edit is simplest
        single_large_edit = [
            {
                "file": "Big.java",
                "start_line": 1,
                "end_line": 1,
                "new_content": "x" * (4 * 1024 * 1024 + 1) + "\n",
                "reason": "too big",
            }
        ]
        tool = self._tool(str(ws_root), str(target))
        result = tool.invoke(
            {"fix_id": self.FIX_ID, "edits": single_large_edit}
        )
        assert "[apply_fix] Error" in result
        # Could be per-edit limit (512KB) or total limit (4MB) — either is correct.
        assert "limit" in result.lower() or "bytes" in result

    def test_oversized_registry_returns_error(self, tmp_path):
        target = tmp_path / "project"
        ws_root = tmp_path / "workspace"
        _write(str(target / "A.java"), "original\n")

        tool = self._tool(str(ws_root), str(target))

        # First call to create workspace.
        tool.invoke(
            {
                "fix_id": self.FIX_ID,
                "edits": [
                    {
                        "file": "A.java",
                        "start_line": 1,
                        "end_line": 1,
                        "new_content": "round1\n",
                        "reason": "r1",
                    }
                ],
            }
        )

        # Corrupt the registry with a large payload.
        ws_path = str(ws_root / "fix" / self.FIX_ID)
        registry = os.path.join(ws_path, ".fix_modified_files")
        with open(registry, "w", encoding="utf-8") as fh:
            fh.write("x" * (2 * 1024 * 1024))  # 2 MB — exceeds 1 MB guard

        # Second call: oversized registry is detected and returns an error.
        result = tool.invoke(
            {
                "fix_id": self.FIX_ID,
                "edits": [
                    {
                        "file": "A.java",
                        "start_line": 1,
                        "end_line": 1,
                        "new_content": "round2\n",
                        "reason": "r2",
                    }
                ],
            }
        )
        assert "[apply_fix] Error" in result
        assert "exceeds" in result

    def test_corrupt_registry_returns_error(self, tmp_path):
        target = tmp_path / "project"
        ws_root = tmp_path / "workspace"
        _write(str(target / "A.java"), "original\n")

        tool = self._tool(str(ws_root), str(target))
        tool.invoke(
            {
                "fix_id": self.FIX_ID,
                "edits": [
                    {
                        "file": "A.java",
                        "start_line": 1,
                        "end_line": 1,
                        "new_content": "round1\n",
                        "reason": "r1",
                    }
                ],
            }
        )

        registry = ws_root / "fix" / self.FIX_ID / ".fix_modified_files"
        registry.write_text("{not valid json", encoding="utf-8")

        result = tool.invoke(
            {
                "fix_id": self.FIX_ID,
                "edits": [
                    {
                        "file": "A.java",
                        "start_line": 1,
                        "end_line": 1,
                        "new_content": "round2\n",
                        "reason": "r2",
                    }
                ],
            }
        )

        assert "[apply_fix] Error" in result
        assert "corrupt or unreadable" in result

    def test_overlapping_edits_rejected(self, tmp_path):
        target = tmp_path / "project"
        ws_root = tmp_path / "workspace"
        _write(str(target / "Overlap.java"), "a\nb\nc\nd\ne\n")
        tool = self._tool(str(ws_root), str(target))
        result = tool.invoke(
            {
                "fix_id": self.FIX_ID,
                "edits": [
                    {
                        "file": "Overlap.java",
                        "start_line": 1,
                        "end_line": 3,
                        "new_content": "new1\n",
                        "reason": "r1",
                    },
                    {
                        "file": "Overlap.java",
                        "start_line": 2,
                        "end_line": 4,
                        "new_content": "new2\n",
                        "reason": "r2",
                    },
                ],
            }
        )
        assert "[apply_fix] Error" in result
        assert "overlap" in result.lower()

    def test_nested_hidden_dir_rejected(self, tmp_path):
        target = tmp_path / "project"
        ws_root = tmp_path / "workspace"
        _write(str(target / "A.java"), "x\n")
        tool = self._tool(str(ws_root), str(target))
        for hidden_path in ("src/.git/config", "com/example/.hidden/Foo.java"):
            result = tool.invoke(
                {
                    "fix_id": self.FIX_ID,
                    "edits": [
                        {
                            "file": hidden_path,
                            "start_line": 1,
                            "end_line": 1,
                            "new_content": "evil\n",
                            "reason": "attack",
                        }
                    ],
                }
            )
            assert (
                "[apply_fix] Error" in result
            ), f"Expected error for {hidden_path!r}"
            assert "hidden" in result

    def test_restore_syncs_deleted_source_file(self, tmp_path):
        """When source is deleted between rounds, workspace copy is removed too."""
        target = tmp_path / "project"
        ws_root = tmp_path / "workspace"
        _write(str(target / "A.java"), "original\n")
        _write(str(target / "B.java"), "other\n")
        tool = self._tool(str(ws_root), str(target))

        # Round 1: modify A.java
        result = tool.invoke(
            {
                "fix_id": self.FIX_ID,
                "edits": [
                    {
                        "file": "A.java",
                        "start_line": 1,
                        "end_line": 1,
                        "new_content": "modified\n",
                        "reason": "r",
                    }
                ],
            }
        )
        assert "Applied" in result

        # Simulate source file deletion
        os.unlink(str(target / "A.java"))

        # Round 2: edit only B.java; A.java should be removed from workspace
        result2 = tool.invoke(
            {
                "fix_id": self.FIX_ID,
                "edits": [
                    {
                        "file": "B.java",
                        "start_line": 1,
                        "end_line": 1,
                        "new_content": "b_edit\n",
                        "reason": "r",
                    }
                ],
            }
        )
        assert "Applied" in result2
        ws_path = ws_root / "fix" / self.FIX_ID
        assert not (
            ws_path / "A.java"
        ).exists(), "Workspace A.java must be removed"
        assert _read(str(ws_path / "B.java")) == "b_edit\n"

        # Registry must not retain the deleted-source entry.
        import json

        registry_path = ws_path / ".fix_modified_files"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        assert (
            "A.java" not in registry
        ), "Deleted-source file must be removed from registry"

    def test_invalid_range_on_second_file_does_not_corrupt_workspace(
        self, tmp_path
    ):
        """P2 regression: validation failure on file B must not leave file A written but unregistered."""
        target = tmp_path / "project"
        ws_root = tmp_path / "workspace"
        _write(str(target / "A.java"), "a1\na2\n")
        _write(str(target / "B.java"), "b1\n")  # 1 line; range [5,5] is invalid

        tool = self._tool(str(ws_root), str(target))

        result = tool.invoke(
            {
                "fix_id": self.FIX_ID,
                "edits": [
                    {
                        "file": "A.java",
                        "start_line": 1,
                        "end_line": 1,
                        "new_content": "MODIFIED\n",
                        "reason": "r",
                    },
                    {
                        "file": "B.java",
                        "start_line": 5,
                        "end_line": 5,
                        "new_content": "oops\n",
                        "reason": "bad",
                    },
                ],
            }
        )
        assert "[apply_fix] Error" in result

        # A.java in workspace must be the original unmodified cache copy.
        ws_a = ws_root / "fix" / self.FIX_ID / "A.java"
        if ws_a.exists():
            assert _read(str(ws_a)) == "a1\na2\n"

        # A second call must be able to apply edits to A.java from original state
        result2 = tool.invoke(
            {
                "fix_id": self.FIX_ID,
                "edits": [
                    {
                        "file": "A.java",
                        "start_line": 1,
                        "end_line": 1,
                        "new_content": "CORRECT\n",
                        "reason": "r",
                    },
                ],
            }
        )
        assert "[apply_fix] Applied" in result2
        assert _read(str(ws_a)) == "CORRECT\na2\n"

    def test_write_failure_rolls_back_written_files(self, tmp_path):
        target = tmp_path / "project"
        ws_root = tmp_path / "workspace"
        _write(str(target / "A.java"), "a1\na2\n")
        _write(str(target / "B.java"), "b1\nb2\n")
        tool = self._tool(str(ws_root), str(target))

        original_write = apply_fix_module._atomic_write_lines
        write_count = [0]

        def flaky_write(path, lines):
            write_count[0] += 1
            if write_count[0] == 2:
                raise OSError("disk full")
            original_write(path, lines)

        with patch(
            "src.tools.apply_fix._atomic_write_lines",
            side_effect=flaky_write,
        ):
            result = tool.invoke(
                {
                    "fix_id": self.FIX_ID,
                    "edits": [
                        {
                            "file": "A.java",
                            "start_line": 1,
                            "end_line": 1,
                            "new_content": "A_REPLACED\n",
                            "reason": "a",
                        },
                        {
                            "file": "B.java",
                            "start_line": 1,
                            "end_line": 1,
                            "new_content": "B_REPLACED\n",
                            "reason": "b",
                        },
                    ],
                }
            )

        assert "[apply_fix] Error" in result
        assert "Rolled back" in result
        ws_path = ws_root / "fix" / self.FIX_ID
        assert _read(str(ws_path / "A.java")) == "a1\na2\n"
        assert _read(str(ws_path / "B.java")) == "b1\nb2\n"

        result2 = tool.invoke(
            {
                "fix_id": self.FIX_ID,
                "edits": [
                    {
                        "file": "A.java",
                        "start_line": 1,
                        "end_line": 1,
                        "new_content": "CORRECT\n",
                        "reason": "r",
                    }
                ],
            }
        )
        assert "[apply_fix] Applied" in result2
        assert _read(str(ws_path / "A.java")) == "CORRECT\na2\n"

    def test_multi_file_batch_edit(self, tmp_path):
        target = tmp_path / "project"
        ws_root = tmp_path / "workspace"
        _write(str(target / "A.java"), "a1\na2\n")
        _write(str(target / "B.java"), "b1\nb2\n")
        tool = self._tool(str(ws_root), str(target))
        result = tool.invoke(
            {
                "fix_id": self.FIX_ID,
                "edits": [
                    {
                        "file": "A.java",
                        "start_line": 1,
                        "end_line": 1,
                        "new_content": "A_REPLACED\n",
                        "reason": "a",
                    },
                    {
                        "file": "B.java",
                        "start_line": 2,
                        "end_line": 2,
                        "new_content": "B_REPLACED\n",
                        "reason": "b",
                    },
                ],
            }
        )
        assert "[apply_fix] Applied 2 edit" in result
        ws_root_path = ws_root / "fix" / self.FIX_ID
        assert _read(str(ws_root_path / "A.java")) == "A_REPLACED\na2\n"
        assert _read(str(ws_root_path / "B.java")) == "b1\nB_REPLACED\n"


# ---------------------------------------------------------------------------
# run_build
# ---------------------------------------------------------------------------


class TestRunBuild:
    FIX_ID = "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d"

    def test_successful_build_returns_succeeded(self, tmp_path):
        ws_root, _ = _setup_workspace(tmp_path, self.FIX_ID)
        tool = make_run_build_tool(ws_root, "echo Build OK")
        result = tool.invoke({"fix_id": self.FIX_ID})
        assert "[run_build] Build succeeded." in result
        assert "Build OK" in result

    def test_failing_build_returns_failed(self, tmp_path):
        ws_root, _ = _setup_workspace(tmp_path, self.FIX_ID)
        cmd = f'"{sys.executable}" -c "import sys; sys.exit(1)"'
        tool = make_run_build_tool(ws_root, cmd)
        result = tool.invoke({"fix_id": self.FIX_ID})
        assert "[run_build] Build failed" in result

    def test_output_truncated_at_200_lines(self, tmp_path):
        ws_root, _ = _setup_workspace(tmp_path, self.FIX_ID)
        py = f'"{sys.executable}"'
        cmd = f"{py} -c \"print('\\n'.join(['x'] * 250))\""
        tool = make_run_build_tool(ws_root, cmd)
        result = tool.invoke({"fix_id": self.FIX_ID})
        assert "Output truncated" in result
        assert "250 lines total" in result

    def test_missing_workspace_returns_error(self, tmp_path):
        ws_root = str(tmp_path / "workspace")
        tool = make_run_build_tool(ws_root, "echo hi")
        result = tool.invoke({"fix_id": self.FIX_ID})
        assert "[run_build] Error" in result

    def test_invalid_fix_id_rejected(self, tmp_path):
        ws_root = str(tmp_path / "workspace")
        tool = make_run_build_tool(ws_root, "echo hi")
        result = tool.invoke({"fix_id": "../../etc/passwd"})
        assert "[run_build] Error" in result
        assert "UUID" in result

    def test_timeout_returns_error(self, tmp_path):
        ws_root, _ = _setup_workspace(tmp_path, self.FIX_ID)
        with patch("src.tools._command_runner.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(
                cmd="sleep", timeout=120
            )
            tool = make_run_build_tool(ws_root, "sleep 999")
            result = tool.invoke({"fix_id": self.FIX_ID})
        assert "timed out" in result
        assert "120" in result

    def test_unexpected_fix_id_rejected(self, tmp_path):
        ws_root, _ = _setup_workspace(tmp_path, self.FIX_ID)
        expected = "11111111-1111-4111-8111-111111111111"
        tool = make_run_build_tool(ws_root, "echo hi", expected_fix_id=expected)
        result = tool.invoke({"fix_id": self.FIX_ID})
        assert "[run_build] Error" in result
        assert "does not match" in result


# ---------------------------------------------------------------------------
# run_tests
# ---------------------------------------------------------------------------


class TestRunTests:
    FIX_ID = "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5e"

    def test_passing_tests_returns_passed(self, tmp_path):
        ws_root, _ = _setup_workspace(tmp_path, self.FIX_ID)
        tool = make_run_tests_tool(ws_root, "echo Tests run: 5, Failures: 0")
        result = tool.invoke({"fix_id": self.FIX_ID})
        assert "[run_tests] Tests passed." in result

    def test_failing_tests_returns_failed(self, tmp_path):
        ws_root, _ = _setup_workspace(tmp_path, self.FIX_ID)
        cmd = f'"{sys.executable}" -c "import sys; sys.exit(2)"'
        tool = make_run_tests_tool(ws_root, cmd)
        result = tool.invoke({"fix_id": self.FIX_ID})
        assert "[run_tests] Tests failed" in result

    def test_missing_workspace_returns_error(self, tmp_path):
        ws_root = str(tmp_path / "workspace")
        tool = make_run_tests_tool(ws_root, "echo hi")
        result = tool.invoke({"fix_id": self.FIX_ID})
        assert "[run_tests] Error" in result

    def test_invalid_fix_id_rejected(self, tmp_path):
        ws_root = str(tmp_path / "workspace")
        tool = make_run_tests_tool(ws_root, "echo hi")
        result = tool.invoke({"fix_id": "notauuid"})
        assert "[run_tests] Error" in result
        assert "UUID" in result

    def test_timeout_returns_error(self, tmp_path):
        ws_root, _ = _setup_workspace(tmp_path, self.FIX_ID)
        with patch("src.tools._command_runner.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(
                cmd="sleep", timeout=300
            )
            tool = make_run_tests_tool(ws_root, "sleep 999")
            result = tool.invoke({"fix_id": self.FIX_ID})
        assert "timed out" in result
        assert "300" in result

    def test_unexpected_fix_id_rejected(self, tmp_path):
        ws_root, _ = _setup_workspace(tmp_path, self.FIX_ID)
        expected = "11111111-1111-4111-8111-111111111111"
        tool = make_run_tests_tool(ws_root, "echo hi", expected_fix_id=expected)
        result = tool.invoke({"fix_id": self.FIX_ID})
        assert "[run_tests] Error" in result
        assert "does not match" in result
