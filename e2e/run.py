"""E2E demo test runner — CLI entry point.

Usage:
    python -m e2e.run                          # Run all scenarios
    python -m e2e.run --scenario startup       # Run one scenario
    python -m e2e.run --list                   # List available scenarios
    python -m e2e.run --gif                    # Record + convert to GIF
    python -m e2e.run --no-record              # Run without recording
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from e2e.harness import LOG_DIR, OUTPUT_DIR, ScenarioResult, cleanup_stale_sessions, run_scenario
from e2e.scenarios import ALL_SCENARIOS

# The demo project root — nv2 should open files from here
DEMO_PROJECT = Path(__file__).parent.parent / "remora_demo" / "project"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="e2e-runner",
        description="Run E2E demo test scenarios with optional recording",
    )
    parser.add_argument(
        "--scenario",
        "-s",
        choices=list(ALL_SCENARIOS.keys()),
        help="Run a specific scenario (default: all)",
    )
    parser.add_argument(
        "--list",
        "-l",
        action="store_true",
        help="List available scenarios and exit",
    )
    parser.add_argument(
        "--gif",
        action="store_true",
        help="Convert recordings to GIF after completion",
    )
    parser.add_argument(
        "--no-record",
        action="store_true",
        help="Run scenario without asciinema recording",
    )
    return parser.parse_args()


def list_scenarios() -> None:
    print("Available E2E scenarios:\n")
    for name, cls in ALL_SCENARIOS.items():
        instance = cls()
        print(f"  {name:15s}  {instance.description}")
    print()


def print_result(result: ScenarioResult) -> None:
    status = "PASS" if result.success else "FAIL"
    print(f"  [{status}] {result.scenario_name} ({result.duration:.1f}s)")
    if result.log_path:
        print(f"         Log:       {result.log_path}")
    if result.cast_path:
        print(f"         Recording: {result.cast_path}")
    if result.gif_path:
        print(f"         GIF:       {result.gif_path}")
    if result.error:
        print(f"         Error:     {result.error}")


def main() -> int:
    args = parse_args()

    if args.list:
        list_scenarios()
        return 0

    # Clean up any orphaned sessions from previous runs
    stale_killed = cleanup_stale_sessions()
    if stale_killed > 0:
        print(f"Cleaned up {stale_killed} stale tmux session(s)")

    # Determine which scenarios to run
    if args.scenario:
        scenario_names = [args.scenario]
    else:
        scenario_names = list(ALL_SCENARIOS.keys())

    # Ensure output directories exist
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    print("E2E Demo Test Runner")
    print(f"  Recording:  {'disabled' if args.no_record else 'enabled'}")
    print(f"  GIF:        {'yes' if args.gif else 'no'}")
    print(f"  Scenarios:  {', '.join(scenario_names)}")
    print(f"  Output:     {OUTPUT_DIR}")
    print(f"  Logs:       {LOG_DIR}")
    print()
    print(f"Tip: LSP client/server logs will be copied to {LOG_DIR}/")
    print("     To monitor all logs in real-time:")
    print(f"     tail -f {LOG_DIR}/server-*.log {LOG_DIR}/client-*.log {LOG_DIR}/e2e-*.log")
    print()

    results: list[ScenarioResult] = []

    for name in scenario_names:
        cls = ALL_SCENARIOS[name]
        scenario = cls()
        print(f"Running: {name} — {scenario.description}")

        result = run_scenario(
            scenario,
            record=not args.no_record,
            gif=args.gif,
            working_dir=DEMO_PROJECT,
        )
        results.append(result)
        print_result(result)
        print()

    # Final cleanup - ensure no sessions are left behind
    final_cleanup = cleanup_stale_sessions()
    if final_cleanup > 0:
        print(f"Warning: Cleaned up {final_cleanup} orphaned session(s) after run")

    # Summary
    passed = sum(1 for r in results if r.success)
    failed = sum(1 for r in results if not r.success)
    print(f"Results: {passed} passed, {failed} failed, {len(results)} total")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
