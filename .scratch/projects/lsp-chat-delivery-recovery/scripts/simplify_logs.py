#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

DEFAULT_LOGS_DIR = Path("/home/andrew/Documents/Projects/remora/.remora/logs")
DEFAULT_DROP_PATTERNS = (
    r"Event NodeDiscoveredEvent .* matched 0 agents: \[\]",
    r"EventBus\.emit: NodeDiscoveredEvent agent_id=None",
    r"EventBus\.emit: 0 handlers for NodeDiscoveredEvent",
)


@dataclass
class FileStats:
    source: str
    destination: str
    total_lines: int = 0
    kept_lines: int = 0
    dropped_lines: int = 0
    dropped_by_pattern: dict[str, int] = field(default_factory=dict)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Remove low-signal lines from Remora logs."
    )
    parser.add_argument(
        "log_files",
        nargs="+",
        help=(
            "Input log files. Absolute paths work directly; relative names are resolved "
            "first from cwd, then from /home/andrew/Documents/Projects/remora/.remora/logs."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory to write simplified logs and summary JSON.",
    )
    parser.add_argument(
        "--suffix",
        default=".simplified",
        help="Suffix inserted before .log in output names (default: .simplified).",
    )
    parser.add_argument(
        "--drop-regex",
        action="append",
        default=[],
        help="Additional regex for lines to drop (can be provided multiple times).",
    )
    parser.add_argument(
        "--keep-empty-files",
        action="store_true",
        help="Write output files even when every line is filtered out.",
    )
    return parser.parse_args()


def expand_inputs(raw_inputs: Iterable[str], logs_root: Path) -> list[Path]:
    resolved: list[Path] = []
    for token in raw_inputs:
        expanded = _expand_single_input(token, logs_root)
        if not expanded:
            raise FileNotFoundError(f"Input not found: {token}")
        resolved.extend(expanded)
    deduped = sorted(set(resolved))
    return deduped


def _expand_single_input(token: str, logs_root: Path) -> list[Path]:
    token_path = Path(token)
    has_glob = any(ch in token for ch in ("*", "?", "["))
    candidates: list[Path] = []

    if token_path.is_absolute():
        if has_glob:
            candidates.extend(sorted(token_path.parent.glob(token_path.name)))
        elif token_path.exists():
            candidates.append(token_path)
        return [path.resolve() for path in candidates if path.is_file()]

    if has_glob:
        candidates.extend(sorted(Path.cwd().glob(token)))
        candidates.extend(sorted(logs_root.glob(token)))
    else:
        cwd_candidate = Path.cwd() / token
        logs_candidate = logs_root / token
        if cwd_candidate.exists():
            candidates.append(cwd_candidate)
        if logs_candidate.exists():
            candidates.append(logs_candidate)

    return [path.resolve() for path in candidates if path.is_file()]


def compile_patterns(extra_patterns: Iterable[str]) -> list[tuple[str, re.Pattern[str]]]:
    patterns = list(DEFAULT_DROP_PATTERNS)
    patterns.extend(extra_patterns)
    compiled: list[tuple[str, re.Pattern[str]]] = []
    for pattern in patterns:
        compiled.append((pattern, re.compile(pattern)))
    return compiled


def simplified_output_name(input_path: Path, suffix: str) -> str:
    if input_path.suffix == ".log":
        return f"{input_path.stem}{suffix}.log"
    return f"{input_path.name}{suffix}"


def simplify_file(
    input_path: Path,
    output_path: Path,
    compiled_patterns: list[tuple[str, re.Pattern[str]]],
    keep_empty_files: bool,
) -> FileStats:
    stats = FileStats(source=str(input_path), destination=str(output_path))
    kept: list[str] = []

    with input_path.open("r", encoding="utf-8", errors="replace") as input_file:
        for line in input_file:
            stats.total_lines += 1
            pattern_label = _first_matching_pattern(line, compiled_patterns)
            if pattern_label is None:
                kept.append(line)
                stats.kept_lines += 1
                continue

            stats.dropped_lines += 1
            stats.dropped_by_pattern[pattern_label] = (
                stats.dropped_by_pattern.get(pattern_label, 0) + 1
            )

    if kept or keep_empty_files:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as output_file:
            output_file.writelines(kept)

    return stats


def _first_matching_pattern(
    line: str, compiled_patterns: list[tuple[str, re.Pattern[str]]]
) -> str | None:
    for label, regex in compiled_patterns:
        if regex.search(line):
            return label
    return None


def write_summary(summary_path: Path, stats: list[FileStats]) -> None:
    payload = {
        "files": [
            {
                "source": stat.source,
                "destination": stat.destination,
                "total_lines": stat.total_lines,
                "kept_lines": stat.kept_lines,
                "dropped_lines": stat.dropped_lines,
                "dropped_by_pattern": stat.dropped_by_pattern,
            }
            for stat in stats
        ],
        "totals": {
            "total_lines": sum(item.total_lines for item in stats),
            "kept_lines": sum(item.kept_lines for item in stats),
            "dropped_lines": sum(item.dropped_lines for item in stats),
        },
    }
    summary_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    output_dir: Path = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        input_files = expand_inputs(args.log_files, DEFAULT_LOGS_DIR)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    compiled_patterns = compile_patterns(args.drop_regex)
    file_stats: list[FileStats] = []

    for input_file in input_files:
        output_name = simplified_output_name(input_file, args.suffix)
        output_file = output_dir / output_name
        stats = simplify_file(
            input_path=input_file,
            output_path=output_file,
            compiled_patterns=compiled_patterns,
            keep_empty_files=args.keep_empty_files,
        )
        file_stats.append(stats)

    summary_path = output_dir / "simplify_summary.json"
    write_summary(summary_path, file_stats)

    for stat in file_stats:
        print(
            f"{Path(stat.source).name}: kept={stat.kept_lines} dropped={stat.dropped_lines} "
            f"total={stat.total_lines}"
        )
    print(f"Summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
