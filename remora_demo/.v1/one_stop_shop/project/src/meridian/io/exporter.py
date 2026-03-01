"""Export helpers for Meridian."""

from __future__ import annotations

import json
from pathlib import Path

from meridian.models import PlanResult


def write_plan(plan: PlanResult, path: Path) -> None:
    """Write a plan to disk as JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = plan.model_dump(mode="json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


__all__ = ["write_plan"]
