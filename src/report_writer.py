"""ReportWriter: terminal summary and JSON persistence for DiagnosisReport."""

import dataclasses
import json
import os
from pathlib import Path

from src.models import DiagnosisReport


def print_summary(report: DiagnosisReport) -> None:
    """Print a human-readable diagnosis summary to stdout.

    Args:
        report: The diagnosis report to summarize.
    """
    print(f"\n{'=' * 60}")
    print(f"Diagnosis ID : {report.diagnosis_id}")
    print(f"Status       : {report.status}")

    if report.conclusion is None:
        print("(Diagnosis not yet complete — no conclusion available)")
        print("=" * 60)
        return

    c = report.conclusion
    confidence_label = {
        "high": "HIGH",
        "medium": "MEDIUM",
        "low": "LOW",
    }.get(c.confidence, c.confidence.upper())

    print(f"\n【根因】{c.root_cause_hypothesis}")
    print(f"\n【置信度】{confidence_label}")
    print(f"        {c.confidence_reason}")
    print(f"\n【修复方向】{c.fix_direction}")

    if c.evidence_refs:
        print("\n【证据】")
        for ref in c.evidence_refs:
            print(f"  - {ref}")

    if c.counter_check:
        print(f"\n【反证检查】{c.counter_check}")

    print("=" * 60)


def write_json(report: DiagnosisReport, path: str | os.PathLike[str]) -> None:
    """Serialize and write a DiagnosisReport to a JSON file.

    Creates parent directories if they do not exist.

    Args:
        report: The diagnosis report to serialize.
        path: Destination file path.
    """
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = dataclasses.asdict(report)
    with dest.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
