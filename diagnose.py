"""CLI entry point for bughunterv2 M1 diagnosis pipeline."""

import argparse
import os
import sys

from src.agent.diagnosis_agent import DiagnosisAgent
from src.config import load_config
from src.report_writer import print_summary, write_json
from src.source_index import SourceIndex
from src.stack_parser import find_business_top_frame, parse_stack_trace


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="diagnose",
        description="Diagnose a Java exception stack trace using static source analysis.",
    )
    parser.add_argument(
        "--stack",
        required=True,
        metavar="FILE",
        help="Path to a file containing the Java exception stack trace.",
    )
    parser.add_argument(
        "--src",
        required=True,
        metavar="DIR",
        help="Root directory of the Java source code to analyse.",
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        metavar="FILE",
        help="Path to the YAML configuration file (default: config.yaml).",
    )
    args = parser.parse_args()

    # validate inputs
    if not os.path.isfile(args.stack):
        print(f"Error: stack trace file not found: {args.stack!r}", file=sys.stderr)
        sys.exit(1)

    if not os.path.isdir(args.src):
        print(f"Error: source directory not found: {args.src!r}", file=sys.stderr)
        sys.exit(1)

    # load config
    config = load_config(args.config)

    # parse stack trace
    with open(args.stack, encoding="utf-8") as f:
        stack_text = f.read()

    frames = parse_stack_trace(stack_text)
    if not frames:
        print("Error: no stack frames found in the provided trace.", file=sys.stderr)
        sys.exit(1)

    if find_business_top_frame(frames, config.framework_packages) is None:
        print(
            "Error: all stack frames belong to framework packages. "
            "Add the relevant packages to framework_packages in config.yaml to exclude them.",
            file=sys.stderr,
        )
        sys.exit(1)

    # build source index
    index = SourceIndex(args.src, extra_roots=config.extra_source_roots)
    index.build()

    # run diagnosis agent
    agent = DiagnosisAgent(config=config, index=index, src_dir=args.src)
    report = agent.run(stack_trace=stack_text, frames=frames)

    # output summary and persist JSON
    print_summary(report)

    out_path = os.path.join("workspace", "diagnosis", f"{report.diagnosis_id}.json")
    write_json(report, out_path)
    print(f"\nFull report written to: {out_path}")


if __name__ == "__main__":
    main()
