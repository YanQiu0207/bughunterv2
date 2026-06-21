"""Unit tests for src/commit/patcher.py."""

import os

import pytest

from src.commit.patcher import (
    apply_edits,
    detect_conflicts,
    generate_diff,
    snapshot_hashes,
)
from src.models import FixEdit


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


def _edit(file: str, start: int, end: int, content: str) -> FixEdit:
    return FixEdit(file=file, start_line=start, end_line=end, new_content=content, reason="test")


# ---------------------------------------------------------------------------
# snapshot_hashes
# ---------------------------------------------------------------------------


class TestSnapshotHashes:
    def test_returns_dict_for_existing_files(self, tmp_path):
        _write(str(tmp_path / "A.java"), "hello\n")
        result = snapshot_hashes(str(tmp_path), ["A.java"])
        assert "A.java" in result
        assert len(result["A.java"]) == 64  # SHA-256 hex

    def test_empty_file_list_returns_empty_dict(self, tmp_path):
        assert snapshot_hashes(str(tmp_path), []) == {}

    def test_missing_file_raises_oserror(self, tmp_path):
        with pytest.raises(OSError):
            snapshot_hashes(str(tmp_path), ["missing.java"])


# ---------------------------------------------------------------------------
# detect_conflicts
# ---------------------------------------------------------------------------


class TestDetectConflicts:
    def test_no_change_returns_empty(self, tmp_path):
        _write(str(tmp_path / "A.java"), "original\n")
        old = snapshot_hashes(str(tmp_path), ["A.java"])
        assert detect_conflicts(old, str(tmp_path)) == []

    def test_changed_file_returned(self, tmp_path):
        _write(str(tmp_path / "A.java"), "original\n")
        old = snapshot_hashes(str(tmp_path), ["A.java"])
        _write(str(tmp_path / "A.java"), "modified\n")
        assert detect_conflicts(old, str(tmp_path)) == ["A.java"]

    def test_missing_file_after_update_returned(self, tmp_path):
        _write(str(tmp_path / "A.java"), "original\n")
        old = snapshot_hashes(str(tmp_path), ["A.java"])
        os.unlink(str(tmp_path / "A.java"))
        assert detect_conflicts(old, str(tmp_path)) == ["A.java"]

    def test_empty_old_hashes_returns_empty(self, tmp_path):
        assert detect_conflicts({}, str(tmp_path)) == []


# ---------------------------------------------------------------------------
# apply_edits
# ---------------------------------------------------------------------------


class TestApplyEdits:
    def test_single_file_single_edit(self, tmp_path):
        _write(str(tmp_path / "A.java"), "line1\nline2\nline3\n")
        apply_edits(str(tmp_path), [_edit("A.java", 2, 2, "REPLACED\n")])
        assert _read(str(tmp_path / "A.java")) == "line1\nREPLACED\nline3\n"

    def test_multi_file_multi_edit(self, tmp_path):
        _write(str(tmp_path / "A.java"), "a1\na2\n")
        _write(str(tmp_path / "B.java"), "b1\nb2\n")
        apply_edits(
            str(tmp_path),
            [
                _edit("A.java", 1, 1, "A_NEW\n"),
                _edit("B.java", 2, 2, "B_NEW\n"),
            ],
        )
        assert _read(str(tmp_path / "A.java")) == "A_NEW\na2\n"
        assert _read(str(tmp_path / "B.java")) == "b1\nB_NEW\n"

    def test_empty_edits_is_noop(self, tmp_path):
        _write(str(tmp_path / "A.java"), "unchanged\n")
        apply_edits(str(tmp_path), [])
        assert _read(str(tmp_path / "A.java")) == "unchanged\n"

    def test_invalid_range_raises_and_rolls_back(self, tmp_path):
        _write(str(tmp_path / "A.java"), "line1\nline2\n")
        _write(str(tmp_path / "B.java"), "b1\n")
        with pytest.raises(ValueError):
            apply_edits(
                str(tmp_path),
                [
                    _edit("A.java", 1, 1, "OK\n"),
                    _edit("B.java", 99, 99, "bad\n"),  # out of range
                ],
            )
        # A.java should be rolled back to original
        assert _read(str(tmp_path / "A.java")) == "line1\nline2\n"


# ---------------------------------------------------------------------------
# generate_diff
# ---------------------------------------------------------------------------


class TestGenerateDiff:
    def test_raises_when_workspace_file_missing(self, tmp_path):
        src = tmp_path / "src"
        ws = tmp_path / "ws"
        _write(str(src / "A.java"), "original\n")
        os.makedirs(str(ws), exist_ok=True)
        with pytest.raises(FileNotFoundError, match="Workspace file not found"):
            generate_diff(str(src), str(ws), ["A.java"])

    def test_diff_produced_when_files_differ(self, tmp_path):
        src = tmp_path / "src"
        ws = tmp_path / "ws"
        _write(str(src / "A.java"), "original\n")
        _write(str(ws / "A.java"), "modified\n")
        diff = generate_diff(str(src), str(ws), ["A.java"])
        assert "original" in diff
        assert "modified" in diff
        assert "a/A.java" in diff

    def test_empty_diff_when_files_identical(self, tmp_path):
        src = tmp_path / "src"
        ws = tmp_path / "ws"
        _write(str(src / "A.java"), "same\n")
        _write(str(ws / "A.java"), "same\n")
        diff = generate_diff(str(src), str(ws), ["A.java"])
        assert diff == ""


# ---------------------------------------------------------------------------
# apply_edits — same-file multiple edits
# ---------------------------------------------------------------------------


class TestSameFileMultipleEdits:
    def test_overlapping_edits_raise_value_error(self, tmp_path):
        _write(str(tmp_path / "A.java"), "line1\nline2\nline3\nline4\n")
        with pytest.raises(ValueError, match="Overlapping"):
            apply_edits(
                str(tmp_path),
                [
                    _edit("A.java", 1, 3, "new\n"),
                    _edit("A.java", 2, 4, "bad\n"),
                ],
            )

    def test_two_edits_same_file_applied_correctly(self, tmp_path):
        _write(str(tmp_path / "A.java"), "line1\nline2\nline3\nline4\nline5\n")
        apply_edits(
            str(tmp_path),
            [
                _edit("A.java", 2, 2, "REPLACED_2\n"),
                _edit("A.java", 4, 4, "REPLACED_4\n"),
            ],
        )
        assert _read(str(tmp_path / "A.java")) == "line1\nREPLACED_2\nline3\nREPLACED_4\nline5\n"


# ---------------------------------------------------------------------------
# Path traversal rejection
# ---------------------------------------------------------------------------


class TestPathTraversal:
    def test_snapshot_hashes_rejects_traversal(self, tmp_path):
        with pytest.raises(ValueError, match="Path traversal detected"):
            snapshot_hashes(str(tmp_path), ["../../etc/passwd"])

    def test_apply_edits_rejects_absolute_path(self, tmp_path):
        with pytest.raises(ValueError, match="Absolute path not allowed"):
            apply_edits(str(tmp_path), [_edit("/etc/passwd", 1, 1, "x\n")])

    def test_apply_edits_rejects_traversal(self, tmp_path):
        with pytest.raises(ValueError, match="Path traversal detected"):
            apply_edits(str(tmp_path), [_edit("../outside.java", 1, 1, "x\n")])
