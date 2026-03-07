"""Verify architecture degree SLOs against the Tach module graph."""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

MAX_OUT_DEGREE = 8
MAX_IN_DEGREE = 12

# Composition roots / intentional barrels currently exempt from hard SLOs.
EXEMPT_MODULES = {
    "remora.cli.main",
    "remora.companion.startup",
    "remora.core",
    "remora.core.agents",
    "remora.core.agents.turn_context",
    "remora.core.events",
    "remora.core.events.agent_events",
    "remora.core.events.interaction_events",
    "remora.core.events.code_events",
    "remora.lsp",
    "remora.lsp.__main__",
    "remora.service.handlers",
}

EDGE_RE = re.compile(r'\s*"([^"]+)"\s*->\s*"([^"]+)"')


def _build_graph() -> tuple[dict[str, int], dict[str, int]]:
    with tempfile.NamedTemporaryFile(prefix="tach_graph_", suffix=".dot", delete=False) as dot_file:
        dot_path = Path(dot_file.name)

    try:
        subprocess.run(["tach", "show", "-o", str(dot_path)], check=True)
        text = dot_path.read_text(encoding="utf-8")
    finally:
        try:
            dot_path.unlink()
        except FileNotFoundError:
            pass

    out_degree: dict[str, int] = {}
    in_degree: dict[str, int] = {}

    for source, target in EDGE_RE.findall(text):
        out_degree[source] = out_degree.get(source, 0) + 1
        in_degree[target] = in_degree.get(target, 0) + 1
        in_degree.setdefault(source, 0)
        out_degree.setdefault(target, 0)

    return in_degree, out_degree


def main() -> int:
    in_degree, out_degree = _build_graph()
    modules = sorted(set(in_degree) | set(out_degree))

    violations: list[str] = []
    for module in modules:
        if module in EXEMPT_MODULES:
            continue

        out_d = out_degree.get(module, 0)
        in_d = in_degree.get(module, 0)

        if out_d > MAX_OUT_DEGREE:
            violations.append(f"OUT-DEGREE: {module} = {out_d} (max {MAX_OUT_DEGREE})")
        if in_d > MAX_IN_DEGREE:
            violations.append(f"IN-DEGREE:  {module} = {in_d} (max {MAX_IN_DEGREE})")

    if violations:
        print("Architecture SLO violations:")
        for violation in violations:
            print(f"  {violation}")
        return 1

    print("Architecture SLOs: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
