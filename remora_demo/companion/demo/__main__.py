"""CLI entry point for the Companion demo harness.

Usage:
    python -m remora_demo.companion.demo
    python -m remora_demo.companion.demo --scenario coding
    python -m remora_demo.companion.demo --scenario research
    python -m remora_demo.companion.demo --list
    python -m remora_demo.companion.demo --capture
    python -m remora_demo.companion.demo --interactive
    python -m remora_demo.companion.demo --record demo.cast
    python -m remora_demo.companion.demo --record demo.cast --gif demo.gif
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Companion demo harness — scripted scenarios with A4-sized rendering",
    )
    parser.add_argument(
        "--scenario",
        choices=["coding", "research", "all"],
        default="all",
        help="Which scenario to run (default: all)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available scenarios and exit",
    )
    parser.add_argument(
        "--capture",
        action="store_true",
        help="Capture frames to .companion/demo_frames/",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Wait for keypress between steps",
    )
    parser.add_argument(
        "--record",
        type=str,
        metavar="FILE",
        help="Record demo to asciicast v2 file (.cast)",
    )
    parser.add_argument(
        "--gif",
        type=str,
        metavar="FILE",
        help="Convert recording to GIF (requires --record or uses auto-named .cast)",
    )
    parser.add_argument(
        "--gif-theme",
        type=str,
        default="dracula",
        help="GIF theme (dracula, monokai, nord, etc.)",
    )
    parser.add_argument(
        "--gif-speed",
        type=float,
        default=1.0,
        help="GIF playback speed multiplier",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Don't write to terminal (recording only)",
    )
    parser.add_argument(
        "--plain",
        type=str,
        metavar="FILE",
        help="Render a single frame to plain text file (no ANSI)",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=100,
        help="Terminal width (default: 100, A4-ish)",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=56,
        help="Terminal height (default: 56, A4-ish)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--workspace",
        type=str,
        help="Custom workspace path (default: built-in examples)",
    )

    args = parser.parse_args()

    # Configure logging
    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format="%(name)s: %(message)s")
    else:
        logging.basicConfig(level=logging.WARNING)

    # Determine examples directory
    if args.workspace:
        examples_dir = Path(args.workspace)
    else:
        examples_dir = Path(__file__).parent.parent / "examples"

    if not examples_dir.exists():
        print(f"Error: workspace directory not found: {examples_dir}", file=sys.stderr)
        return 1

    # Import scenarios
    from remora_demo.companion.demo.scenarios import (
        coding_scenario,
        get_all_scenarios,
        research_scenario,
    )

    # List mode
    if args.list:
        scenarios = get_all_scenarios(examples_dir)
        print("Available demo scenarios:")
        print()
        for s in scenarios:
            print(f"  {s.name}")
            print(f"    {s.description}")
            print(f"    Steps: {len(s.steps)}")
            print()
        return 0

    # Select scenarios
    if args.scenario == "coding":
        scenarios = [coding_scenario(examples_dir)]
    elif args.scenario == "research":
        scenarios = [research_scenario(examples_dir)]
    else:
        scenarios = get_all_scenarios(examples_dir)

    # Build config
    from remora_demo.companion.demo.harness import DemoConfig
    from remora_demo.companion.demo.renderer import RenderConfig

    render_config = RenderConfig(
        total_width=args.width,
        total_height=args.height,
    )

    demo_config = DemoConfig(
        render=render_config,
        capture_frames=args.capture,
        interactive=args.interactive,
        record_cast=Path(args.record) if args.record else None,
        record_gif=Path(args.gif) if args.gif else None,
        gif_theme=args.gif_theme,
        gif_speed=args.gif_speed,
        headless=args.headless,
    )

    # Run
    harness = None
    try:
        from remora_demo.companion.demo.harness import DemoHarness

        harness = DemoHarness(demo_config)
        results = asyncio.run(harness.run_all_scenarios(scenarios))

        # Report outputs
        for i, outputs in enumerate(results):
            if outputs:
                scenario_name = scenarios[i].name
                for kind, path in outputs.items():
                    print(f"  [{scenario_name}] {kind}: {path}")

    except KeyboardInterrupt:
        print(f"\n{' ' * 2}Demo interrupted.")
    finally:
        if harness:
            # Ensure terminal is restored
            sys.stdout.write("\033[?25h\033[0m")
            sys.stdout.flush()

    return 0


if __name__ == "__main__":
    sys.exit(main())
