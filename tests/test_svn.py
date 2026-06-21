"""Unit tests for src/commit/svn.py."""

from unittest.mock import MagicMock, patch

import pytest

from src.commit.svn import svn_commit, svn_dirty_files, svn_revert, svn_update


class TestSvnUpdate:
    def test_calls_svn_update_in_path(self, tmp_path):
        with patch("src.commit.svn.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            svn_update(str(tmp_path))
            mock_run.assert_called_once()
            args = mock_run.call_args
            assert args[0][0] == ["svn", "update"]
            assert args[1]["cwd"] == str(tmp_path)

    def test_raises_on_nonzero_exit(self, tmp_path):
        with patch("src.commit.svn.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="E000: error")
            with pytest.raises(RuntimeError, match="svn update failed"):
                svn_update(str(tmp_path))


class TestSvnCommit:
    def test_returns_revision_number(self, tmp_path):
        with patch("src.commit.svn.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="Committed revision 42.\n",
                stderr="",
            )
            revision = svn_commit(str(tmp_path), "fix: null check", ["A.java"])
            assert revision == "42"

    def test_returns_question_mark_when_revision_unparseable(self, tmp_path):
        with patch("src.commit.svn.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="No output", stderr=""
            )
            assert svn_commit(str(tmp_path), "msg", ["A.java"]) == "?"

    def test_raises_on_nonzero_exit(self, tmp_path):
        with patch("src.commit.svn.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="E200009")
            with pytest.raises(RuntimeError, match="svn commit failed"):
                svn_commit(str(tmp_path), "msg", ["A.java"])

    def test_passes_only_specified_files(self, tmp_path):
        with patch("src.commit.svn.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="Committed revision 1.\n", stderr=""
            )
            svn_commit(str(tmp_path), "fix", ["src/Foo.java", "src/Bar.java"])
            cmd = mock_run.call_args[0][0]
            assert "--" in cmd
            assert "src/Foo.java" in cmd
            assert "src/Bar.java" in cmd


class TestSvnRevert:
    def test_calls_revert_with_file_list(self, tmp_path):
        with patch("src.commit.svn.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            svn_revert(str(tmp_path), ["A.java", "B.java"])
            args = mock_run.call_args[0][0]
            assert "svn" in args
            assert "revert" in args
            assert "A.java" in args
            assert "B.java" in args

    def test_raises_on_nonzero_exit(self, tmp_path):
        with patch("src.commit.svn.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="E200009")
            with pytest.raises(RuntimeError, match="svn revert failed"):
                svn_revert(str(tmp_path), ["A.java"])

    def test_empty_file_list_skips_subprocess(self, tmp_path):
        with patch("src.commit.svn.subprocess.run") as mock_run:
            svn_revert(str(tmp_path), [])
            mock_run.assert_not_called()


class TestSvnDirtyFiles:
    def test_returns_empty_when_all_clean(self, tmp_path):
        with patch("src.commit.svn.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
            assert svn_dirty_files(str(tmp_path), ["A.java"]) == []

    def test_returns_modified_file(self, tmp_path):
        with patch("src.commit.svn.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="M       A.java\n", stderr=""
            )
            dirty = svn_dirty_files(str(tmp_path), ["A.java"])
            assert "A.java" in dirty

    def test_ignores_unversioned_files(self, tmp_path):
        with patch("src.commit.svn.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="?       Untracked.java\n", stderr=""
            )
            assert svn_dirty_files(str(tmp_path), ["Untracked.java"]) == []

    def test_raises_on_nonzero_exit(self, tmp_path):
        with patch("src.commit.svn.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1, stdout="", stderr="not a working copy"
            )
            with pytest.raises(RuntimeError, match="svn status failed"):
                svn_dirty_files(str(tmp_path), ["A.java"])

    def test_empty_file_list_skips_subprocess(self, tmp_path):
        with patch("src.commit.svn.subprocess.run") as mock_run:
            result = svn_dirty_files(str(tmp_path), [])
            mock_run.assert_not_called()
            assert result == []
