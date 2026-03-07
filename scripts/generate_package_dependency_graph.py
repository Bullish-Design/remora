"""Generate a top-level package dependency graph from a Tach DOT graph."""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

EDGE_RE = re.compile(r'\s*"([^"]+)"\s*->\s*"([^"]+)"')

DEFAULT_INPUT = Path("tach_module_graph.dot")
DEFAULT_OUTPUT = Path("docs/graphs/remora_package_dependencies.dot")

# Keep common packages grouped in a predictable order.
PREFERRED_NODE_ORDER = (
    "__main__",
    "cli",
    "lsp",
    "service",
    "runner",
    "core",
    "ui",
    "companion",
    "workspace",
    "models",
    "utils",
    "adapters",
    "extensions",
)


def _top_package(module: str) -> str | None:
    if module == "remora.__main__":
        return "__main__"
    if not module.startswith("remora."):
        return None
    parts = module.split(".")
    if len(parts) < 2:
        return None
    if parts[1] == "__main__":
        return "__main__"
    return parts[1]


def parse_cross_package_edges(dot_text: str) -> Counter[tuple[str, str]]:
    edge_counts: Counter[tuple[str, str]] = Counter()
    for source, target in EDGE_RE.findall(dot_text):
        source_pkg = _top_package(source)
        target_pkg = _top_package(target)
        if source_pkg is None or target_pkg is None:
            continue
        if source_pkg == target_pkg:
            continue
        edge_counts[(source_pkg, target_pkg)] += 1
    return edge_counts


def _node_sort_key(node: str) -> tuple[int, str]:
    try:
        return (PREFERRED_NODE_ORDER.index(node), node)
    except ValueError:
        return (len(PREFERRED_NODE_ORDER), node)


def _node_id(node: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_]+", "_", node)
    return f"n_{sanitized}"


def _node_label(node: str) -> str:
    if node == "__main__":
        return "remora.__main__"
    return f"remora.{node}"


def _penwidth(count: int, max_count: int) -> str:
    if count <= 1:
        return "1.0"
    # Keep dense edges readable without exploding width.
    width = 1.0 + (count / max_count) * 2.6
    return f"{width:.1f}"


def render_dot(edge_counts: Counter[tuple[str, str]], min_count: int = 1) -> str:
    filtered_edges = [
        (source, target, count)
        for (source, target), count in edge_counts.items()
        if count >= min_count
    ]
    filtered_edges.sort(key=lambda item: (item[0], item[1]))

    nodes = sorted({source for source, _, _ in filtered_edges} | {target for _, target, _ in filtered_edges}, key=_node_sort_key)
    node_ids = {node: _node_id(node) for node in nodes}
    max_count = max((count for _, _, count in filtered_edges), default=1)

    lines: list[str] = [
        "digraph RemoraPackageDependencies {",
        '  graph [rankdir=LR, splines=true, fontname="Helvetica", fontsize=11, labelloc="t", label="Remora Top-Level Package Dependencies\\n(aggregated from tach_module_graph.dot)"];',
        '  node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=10, fillcolor="#f8fafc", color="#334155"];',
        '  edge [color="#475569", arrowsize=0.7];',
        "",
    ]

    for node in nodes:
        attributes = [f'label="{_node_label(node)}"']
        if node == "core":
            attributes.append('fillcolor="#e2e8f0"')
        lines.append(f'  {node_ids[node]} [{", ".join(attributes)}];')

    if nodes:
        lines.append("")

    for source, target, count in filtered_edges:
        attributes = [f'label="{count}"', f'penwidth={_penwidth(count, max_count)}']
        if count == 1:
            attributes.append("style=dashed")
        lines.append(f"  {node_ids[source]} -> {node_ids[target]} [{', '.join(attributes)}];")

    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def generate_package_graph(input_path: Path, output_path: Path, min_count: int = 1) -> None:
    dot_text = input_path.read_text(encoding="utf-8")
    edge_counts = parse_cross_package_edges(dot_text)
    rendered = render_dot(edge_counts=edge_counts, min_count=min_count)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate docs/graphs/remora_package_dependencies.dot from tach_module_graph.dot.",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="Path to a Tach DOT graph (default: tach_module_graph.dot).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output DOT path (default: docs/graphs/remora_package_dependencies.dot).",
    )
    parser.add_argument(
        "--min-count",
        type=int,
        default=1,
        help="Minimum aggregated edge count to include (default: 1).",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    generate_package_graph(input_path=args.input, output_path=args.output, min_count=args.min_count)
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
