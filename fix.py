"""CLI entry point for bughunterv2 M2 fix pipeline."""

import argparse
import json
import os
import sys

from src.agent.fix_agent import FixAgent
from src.config import load_config
from src.models import Conclusion, DiagnosisInput, DiagnosisReport, FixProposal


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="fix",
        description="Generate a fix for a Java bug from a diagnosis report.",
    )
    parser.add_argument(
        "--report",
        required=True,
        metavar="FILE",
        help="Path to a diagnosis JSON produced by diagnose.py.",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        metavar="FILE",
        help="Path to the YAML configuration file (default: config.yaml).",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.report):
        print(f"Error: report file not found: {args.report!r}", file=sys.stderr)
        sys.exit(1)

    config = load_config(args.config)
    config.svn_cache_dir = _resolve_config_relative_path(
        config.svn_cache_dir,
        args.config,
    )

    missing = [
        name
        for name, val in (
            ("target_project_dir", config.target_project_dir),
            ("svn_cache_dir", config.svn_cache_dir),
            ("build_command", config.build_command),
            ("test_command", config.test_command),
        )
        if not val
    ]
    if missing:
        print(
            f"Error: the following config fields are required for fix.py but are "
            f"empty: {', '.join(missing)}\n"
            f"Edit {args.config!r} to fill them in.",
            file=sys.stderr,
        )
        sys.exit(1)

    report = _load_report(args.report)
    workspace_root = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "workspace"
    )

    agent = FixAgent(config=config, workspace_root=workspace_root)
    proposal = agent.run(report)

    _print_summary(proposal, workspace_root)


def _load_report(path: str) -> DiagnosisReport:
    """Deserialise a DiagnosisReport from a JSON checkpoint file.

    Args:
        path: Path to the JSON file produced by diagnose.py.

    Returns:
        DiagnosisReport populated from the file.

    Raises:
        SystemExit: If the file cannot be parsed.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Error: cannot read report file: {exc}", file=sys.stderr)
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
        diagnosis_id=data.get("diagnosis_id", ""),
        created_at=data.get("created_at", ""),
        status=data.get("status", "completed"),
        input=DiagnosisInput(
            stack_trace=inp.get("stack_trace", ""),
            source_dir=inp.get("source_dir", ""),
        ),
        conclusion=conclusion,
    )


def _resolve_config_relative_path(path: str, config_path: str) -> str:
    """Resolve a config path relative to the config file location."""
    if not path or os.path.isabs(path):
        return path
    config_dir = os.path.dirname(os.path.abspath(config_path))
    return os.path.abspath(os.path.join(config_dir, path))


def _print_summary(proposal: FixProposal, workspace_root: str) -> None:
    """Print a human-readable fix summary to stdout."""
    print("\n" + "=" * 60)
    print(f"Fix Proposal: {proposal.proposal_id}")
    print(f"Diagnosis  : {proposal.diagnosis_id}")
    print(f"Status     : {proposal.status.upper()}")
    print(f"Summary    : {proposal.summary}")

    if proposal.edits:
        affected = sorted({e.file for e in proposal.edits})
        print(f"\nModified files ({len(affected)}):")
        for f in affected:
            print(f"  {f}")

    json_path = os.path.join(
        workspace_root, "fix", f"{proposal.proposal_id}.json"
    )
    workspace_path = os.path.join(workspace_root, "fix", proposal.proposal_id)
    print(f"\nFull proposal : {json_path}")
    print(f"Workspace     : {workspace_path}")

    if proposal.status == "verified":
        print(
            "\n✔ Build and unit tests passed in the isolated workspace.\n"
            "  Review the workspace, then write back when ready:\n"
            f"  python .\\commit_fix.py {proposal.proposal_id} --dry-run\n"
            f"  python .\\commit_fix.py {proposal.proposal_id} --yes"
        )
    else:
        print(
            "\n⚠ Proposal is a best-effort draft (build/tests did not fully pass).\n"
            "  Review the workspace and iterate manually if needed.\n"
            "  When ready, use commit_fix.py --dry-run / --yes to write back."
        )
    print("=" * 60)


if __name__ == "__main__":
    main()
