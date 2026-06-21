"""CLI entry point for bughunterv2 M3 commit pipeline."""

import argparse
import json
import os
import pathlib
import re
import shlex
import subprocess
import sys
import uuid

from filelock import FileLock, Timeout as FileLockTimeout

from src.agent.fix_agent import FixAgent
from src.commit.patcher import apply_edits, detect_conflicts, generate_diff, snapshot_hashes
from src.commit.svn import svn_commit, svn_dirty_files, svn_revert, svn_update
from src.config import load_config
from src.models import (
    Conclusion,
    DiagnosisInput,
    DiagnosisReport,
    FixEdit,
    FixProposal,
)


def _revert_and_abort(source_dir: str, files: list[str], msg: str) -> None:
    """Print error, attempt svn_revert, then sys.exit(1)."""
    print(f"Error: {msg}", file=sys.stderr)
    try:
        svn_revert(source_dir, files)
    except Exception as revert_exc:
        print(f"Warning: svn revert also failed: {revert_exc}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="commit_fix",
        description="Apply a verified fix proposal to the SVN working copy and commit.",
    )
    parser.add_argument(
        "proposal_id",
        help="UUID of the FixProposal to commit (must have status='verified').",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        metavar="FILE",
        help="Path to the YAML configuration file (default: config.yaml).",
    )
    parser.add_argument(
        "--max-retry",
        type=int,
        default=None,
        metavar="N",
        help="Maximum fix-agent retries on conflict (overrides config).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the unified diff and exit without modifying any files.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Apply edits and commit after showing the diff (required to proceed).",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    max_retry = args.max_retry if args.max_retry is not None else config.max_retry
    workspace_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workspace")

    _run_with_workspace(workspace_root, args.proposal_id, config, max_retry, args.dry_run, args.yes)


def _run_with_workspace(
    workspace_root: str,
    proposal_id: str,
    config: object,
    max_retry: int,
    dry_run: bool,
    yes: bool = False,
) -> None:
    """Core commit loop, extracted for testability.

    Args:
        workspace_root: Root workspace directory.
        proposal_id: UUID of the FixProposal to commit.
        config: Loaded Config object.
        max_retry: Maximum number of conflict-retry attempts.
        dry_run: If True, print diff and exit without writing files.
        yes: If False (default), print diff and exit; requires --yes to proceed.
    """
    source_dir = config.target_project_dir  # type: ignore[attr-defined]

    proposal = _load_proposal(workspace_root, proposal_id)
    if proposal.status != "verified":
        print(
            f"Error: proposal '{proposal_id}' has status='{proposal.status}'. "
            "Only 'verified' proposals may be committed.",
            file=sys.stderr,
        )
        sys.exit(1)

    diagnosis = _load_diagnosis(workspace_root, proposal.diagnosis_id)

    current_ws_root = workspace_root
    lock_path = os.path.join(source_dir, ".bughunter.lock")
    try:
        with FileLock(lock_path, timeout=0):
            for attempt in range(max_retry + 1):
                workspace_dir = os.path.join(current_ws_root, "fix", proposal.proposal_id)
                edited_files = list({e.file for e in proposal.edits})

                dirty = svn_dirty_files(source_dir, edited_files)
                if dirty:
                    print(
                        f"Error: {len(dirty)} file(s) targeted by the fix have uncommitted "
                        f"local changes: {', '.join(dirty)}. Commit or revert these changes "
                        "before proceeding.",
                        file=sys.stderr,
                    )
                    sys.exit(1)

                try:
                    old_hashes = snapshot_hashes(source_dir, edited_files)
                except OSError as exc:
                    print(f"Error: cannot read source files: {exc}", file=sys.stderr)
                    sys.exit(1)
                try:
                    svn_update(source_dir)
                except RuntimeError as exc:
                    print(f"Error: {exc}", file=sys.stderr)
                    sys.exit(1)

                conflicts = detect_conflicts(old_hashes, source_dir)
                if conflicts:
                    if attempt < max_retry:
                        print(
                            f"[commit_fix] Conflict on attempt {attempt + 1}/{max_retry + 1} "
                            f"({len(conflicts)} file(s) changed by SVN update). "
                            "Re-running fix agent...",
                            file=sys.stderr,
                        )
                        new_ws_root = os.path.join(workspace_root, f"retry-{uuid.uuid4()}")
                        agent = FixAgent(config=config, workspace_root=new_ws_root)
                        proposal = agent.run(diagnosis)
                        if proposal.status != "verified":
                            print(
                                "Error: fix agent returned a draft proposal during retry. Aborting.",
                                file=sys.stderr,
                            )
                            sys.exit(1)
                        current_ws_root = new_ws_root
                        continue
                    else:
                        _revert_and_abort(
                            source_dir,
                            edited_files,
                            f"conflict persists after {max_retry} retries "
                            f"({len(conflicts)} file(s) still changed).",
                        )

                try:
                    diff_text = generate_diff(source_dir, workspace_dir, edited_files)
                except FileNotFoundError as exc:
                    print(f"Error: {exc}", file=sys.stderr)
                    sys.exit(1)
                print(diff_text)

                if dry_run:
                    print("[commit_fix] Dry-run: no files written.", file=sys.stderr)
                    sys.exit(0)

                if not yes:
                    print(
                        "[commit_fix] Diff shown above. Pass --yes to apply and commit.",
                        file=sys.stderr,
                    )
                    sys.exit(0)

                try:
                    apply_edits(source_dir, proposal.edits)
                except Exception as exc:
                    _revert_and_abort(source_dir, edited_files, f"failed to apply edits: {exc}")

                for label, cmd in [
                    ("build", config.build_command),  # type: ignore[attr-defined]
                    ("test", config.test_command),  # type: ignore[attr-defined]
                ]:
                    if not cmd:
                        continue
                    proc = subprocess.run(shlex.split(cmd), cwd=source_dir, capture_output=True, text=True)
                    if proc.returncode != 0:
                        output = (proc.stdout + proc.stderr)[-2000:]
                        _revert_and_abort(
                            source_dir,
                            edited_files,
                            f"{label} failed after applying edits:\n{output}",
                        )

                message = f"[bughunter] {proposal.summary[:200]}"
                try:
                    revision = svn_commit(source_dir, message, edited_files)
                except Exception as exc:
                    _revert_and_abort(source_dir, edited_files, f"svn commit failed: {exc}")

                print(f"[commit_fix] Committed: r{revision}")
                return
    except FileLockTimeout:
        print(
            "Error: another commit_fix is already running against this working copy. "
            "Please try again later.",
            file=sys.stderr,
        )
        sys.exit(1)


_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _load_proposal(workspace_root: str, proposal_id: str) -> FixProposal:
    """Deserialise a FixProposal from its JSON checkpoint file.

    Args:
        workspace_root: Root workspace directory.
        proposal_id: UUID of the proposal.

    Returns:
        FixProposal populated from the checkpoint.

    Raises:
        SystemExit: If the file cannot be found or parsed.
    """
    if not _UUID_RE.match(proposal_id):
        print(
            f"Error: invalid proposal_id {proposal_id!r}: must be a UUID.",
            file=sys.stderr,
        )
        sys.exit(1)
    path = os.path.join(workspace_root, "fix", f"{proposal_id}.json")
    if not os.path.isfile(path):
        print(f"Error: proposal file not found: {path!r}", file=sys.stderr)
        sys.exit(1)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Error: cannot read proposal file: {exc}", file=sys.stderr)
        sys.exit(1)

    edits = []
    for e in data.get("edits", []):
        if not isinstance(e, dict):
            continue
        file_val = str(e.get("file", ""))
        if os.path.isabs(file_val) or ".." in pathlib.PurePath(file_val).parts:
            print(
                f"Error: proposal contains invalid file path: {file_val!r}. "
                "Paths must be relative and must not escape the project root.",
                file=sys.stderr,
            )
            sys.exit(1)
        edits.append(FixEdit(
            file=file_val,
            start_line=int(e.get("start_line", 0)),
            end_line=int(e.get("end_line", 0)),
            new_content=str(e.get("new_content", "")),
            reason=str(e.get("reason", "")),
        ))
    return FixProposal(
        proposal_id=str(data.get("proposal_id", proposal_id)),
        diagnosis_id=str(data.get("diagnosis_id", "")),
        created_at=str(data.get("created_at", "")),
        status=str(data.get("status", "draft")),
        edits=edits,
        summary=str(data.get("summary", "")),
    )


def _load_diagnosis(workspace_root: str, diagnosis_id: str) -> DiagnosisReport:
    """Deserialise a DiagnosisReport from its JSON checkpoint file.

    Args:
        workspace_root: Root workspace directory.
        diagnosis_id: UUID of the diagnosis.

    Returns:
        DiagnosisReport populated from the checkpoint.

    Raises:
        SystemExit: If the file cannot be found or parsed.
    """
    path = os.path.join(workspace_root, "diagnosis", f"{diagnosis_id}.json")
    if not os.path.isfile(path):
        print(f"Error: diagnosis file not found: {path!r}", file=sys.stderr)
        sys.exit(1)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Error: cannot read diagnosis file: {exc}", file=sys.stderr)
        sys.exit(1)

    conclusion: Conclusion | None = None
    if data.get("conclusion"):
        c = data["conclusion"]
        conclusion = Conclusion(
            root_cause_hypothesis=c.get("root_cause_hypothesis", ""),
            evidence_refs=c.get("evidence_refs", []),
            counter_check=c.get("counter_check", ""),
            fix_direction=c.get("fix_direction", ""),
            confidence=c.get("confidence", "low"),
            confidence_reason=c.get("confidence_reason", ""),
        )

    inp = data.get("input", {})
    return DiagnosisReport(
        diagnosis_id=str(data.get("diagnosis_id", diagnosis_id)),
        created_at=str(data.get("created_at", "")),
        status=str(data.get("status", "completed")),
        input=DiagnosisInput(
            stack_trace=inp.get("stack_trace", ""),
            source_dir=inp.get("source_dir", ""),
        ),
        conclusion=conclusion,
    )


if __name__ == "__main__":
    main()
