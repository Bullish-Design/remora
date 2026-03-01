"""CLI entry point for Meridian."""

from __future__ import annotations

import argparse
from pathlib import Path

from meridian.config import PlannerConfig
from meridian.io.exporter import write_plan
from meridian.io.loader import load_dataset
from meridian.pipeline import MeridianPlanner


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Meridian planning pipeline")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "data",
        help="Path to sample data directory",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("meridian_plan.json"),
        help="Output JSON path",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    config = PlannerConfig.from_env()
    dataset = load_dataset(args.data_dir)
    planner = MeridianPlanner(config)
    plan = planner.plan(dataset)

    write_plan(plan, args.output)

    print("Meridian plan generated")
    print(f"Output: {args.output}")
    print(f"Reorder lines: {len(plan.recommendations)}")
    print(f"Pricing updates: {len(plan.pricing)}")


if __name__ == "__main__":
    main()
