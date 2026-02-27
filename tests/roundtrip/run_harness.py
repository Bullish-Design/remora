#!/usr/bin/env python3
"""Round-trip test harness for the discovery pipeline.

For each .py file in input/, runs tree-sitter discovery and writes the
matched text (or error output) to output/<filename>_out.

If a file produces multiple matches of the same node type, each match is
saved as <filename>_out-<num> (1-indexed).

Usage:
    uv run python tests/roundtrip/run_harness.py
    uv run python tests/roundtrip/run_harness.py --node-type function
    uv run python tests/roundtrip/run_harness.py --node-type method --node-type class

Check the output/ directory to see what was discovered.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from remora.discovery import NodeType, discover

HARNESS_DIR = Path(__file__).resolve().parent
INPUT_DIR = HARNESS_DIR / "input"
OUTPUT_DIR = HARNESS_DIR / "output"


def main() -> None:
    parser = argparse.ArgumentParser(description="Round-trip discovery test harness")
    parser.add_argument(
        "--node-type",
        action="append",
        choices=[nt.value for nt in NodeType],
        help="Filter by node type (can specify multiple). Default: all types.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove output/ directory before running.",
    )
    args = parser.parse_args()

    filter_types: set[str] | None = set(args.node_type) if args.node_type else None

    if not INPUT_DIR.is_dir():
        print(f"ERROR: Input directory not found: {INPUT_DIR}")
        print("Create it and add .py files to test against.")
        sys.exit(1)

    if args.clean and OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(exist_ok=True)

    input_files = sorted(INPUT_DIR.glob("*.py"))
    if not input_files:
        print(f"No .py files found in {INPUT_DIR}")
        sys.exit(0)

    print(f"Harness: {len(input_files)} input file(s)")
    print(f"Filter: {filter_types or 'all node types'}")
    print(f"Output: {OUTPUT_DIR}\n")

    total_matches = 0

    for input_file in input_files:
        stem = input_file.stem
        print(f"-- {input_file.name} ", end="")

        try:
            nodes = discover([input_file], languages=["python"], node_types=list(filter_types) if filter_types else None)

            if not nodes:
                out_path = OUTPUT_DIR / f"{stem}_out"
                out_path.write_text("(no matches)\n", encoding="utf-8")
                print("-> 0 matches")
                continue

            if len(nodes) == 1:
                out_path = OUTPUT_DIR / f"{stem}_out"
                out_path.write_text(
                    _format_node(nodes[0]),
                    encoding="utf-8",
                )
                total_matches += 1
            else:
                for i, node in enumerate(nodes, start=1):
                    out_path = OUTPUT_DIR / f"{stem}_out-{i}"
                    out_path.write_text(
                        _format_node(node),
                        encoding="utf-8",
                    )
                total_matches += len(nodes)

            print(f"-> {len(nodes)} match(es)")

        except Exception as exc:
            out_path = OUTPUT_DIR / f"{stem}_out"
            out_path.write_text(
                f"ERROR: {exc}\n\n{traceback.format_exc()}",
                encoding="utf-8",
            )
            print(f"-> ERROR: {exc}")

    print(f"\nDone. {total_matches} total match(es) written to {OUTPUT_DIR}")


def _format_node(node) -> str:
    """Format a CSTNode for output."""
    header = (
        f"node_type: {node.node_type}\n"
        f"name: {node.name}\n"
        f"full_name: {node.full_name}\n"
        f"node_id: {node.node_id}\n"
        f"file_path: {node.file_path}\n"
        f"lines: {node.start_line}-{node.end_line}\n"
        f"bytes: {node.start_byte}-{node.end_byte}\n"
        f"---\n"
    )
    return header + node.text + "\n"


if __name__ == "__main__":
    main()
